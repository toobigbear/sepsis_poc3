# -*- coding: utf-8 -*-
"""T3 多专科 Agent 会诊（MANTA 收敛版，适配二期地基）。

思想来源：图A5 MANTA——多Agent的"谁先发言、谁向谁取证、谁交叉核验"按病例
复杂度动态调整。三期收敛为"4 个固定专科角色 + 动态通信路径"（保医疗可解释性）。

与二期地基的衔接：
- 取证用二期 Storage.bm25_search（viking:// URI，引用可溯源、可校验）；
- 每个专科 Agent 只在本专科文档集合内检索（T4 按需装载：专科文档=能力边界）；
- LLM 用二期 ChatLLM（三级降级链 + OfflineBrain，后端没起也能演示）；
- 红线用二期 Guardrail（is_boundary_request / final_check）；
- 置信度用三期 confidence（基于实际 Read 的 viking URI 信号）。

四个固定专科角色 → 各自负责的指南文档（能力边界，T4 按需装载）：
- 住院 resident：诊断标准 + SOFA + 器官功能（逐项核查、时间窗）
- 药师 pharmacist：抗菌药物 + 感染源控制（用药与药学监护视角）
- 护理 nurse：液体复苏/血管活性 + SSC时间窗（监护趋势、液体平衡）
- 主治 attending：综合（可取全部文档，做多学科结论）
"""
from __future__ import annotations

import os
import re
from typing import Dict, List

import config
from vikingrag.llm import LLM, approx_tokens
from vikingrag.storage import Storage
from src.guardrails import Guardrail
from src import confidence

# 专科 → 负责的指南文档名（viking://<doc>/... 的 <doc> 前缀）
ROLE_DOCS = {
    "resident":   ["sepsis3_definition", "sofa_scoring", "organ_dysfunction_criteria", "ssc_guideline_2021"],
    "pharmacist": ["antibiotics_guideline", "source_control_culture", "fluid_and_vasoactive"],
    "nurse":      ["fluid_and_vasoactive", "ssc_guideline_2021", "organ_dysfunction_criteria"],
    "attending":  None,   # 主治可取全部
}
ROLE_CN = {"resident": "住院医师", "pharmacist": "临床药师",
           "nurse": "专科护理", "attending": "主治医师"}
ROLE_FOCUS = {
    "resident": "逐项核查SOFA各系统、识别器官功能障碍、核对1小时集束化时间窗",
    "pharmacist": "从抗感染用药与药学监护角度审阅，关注覆盖/降阶梯/培养/肾毒性",
    "nurse": "从监护趋势、液体平衡、血管活性药物变化、时间窗执行角度补充",
    "attending": "综合各专科意见，形成多学科循证评估结论",
}


def _patient_text(patient: dict) -> str:
    """真实 schema 组织病例描述。"""
    vitals = "；".join(f"{k} {v}" for k, v in patient.get("vitals", {}).items())
    labs = "；".join(f"{k} {v}" for k, v in patient.get("labs", {}).items())
    return (f"{patient.get('patient_id')} {patient.get('demographics','')} "
            f"主诉:{patient.get('chief_complaint','')} 生命体征:{vitals} "
            f"化验:{labs} 影像:{patient.get('imaging','')} 病史:{patient.get('clinical_note','')}")


def assess_severity(patient: dict) -> int:
    """按生命体征粗估严重度（解析带单位的中文字符串里的数值）。"""
    text = _patient_text(patient)
    score = 0
    lac = _num(text, r"乳酸[^\d]{0,4}(\d+\.?\d*)")
    mapv = _num(text, r"MAP\s*(\d+\.?\d*)") or _num(text, r"(\d+)/\d+\s*mmHg")
    gcs = _num(text, r"GCS\s*(\d+)")
    if lac and lac >= 4: score += 2
    elif lac and lac > 2: score += 1
    if mapv and mapv < 65: score += 2
    if gcs and gcs < 13: score += 1
    if re.search(r"去甲肾上腺素|血管活性|升压", text): score += 2
    return score


def _num(text, pattern):
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


class SpecialistAgent:
    """单个专科 Agent：只在本专科文档内取证（T4 能力边界）。"""

    def __init__(self, role: str, storage: Storage):
        self.role = role
        self.st = storage
        self.evidence_uris: List[str] = []

    def retrieve(self, query: str, top_k: int = 4):
        """在本专科文档集合内 BM25 取证，返回实际 Read 的 viking URI 与证据文本。"""
        docs = ROLE_DOCS.get(self.role)
        hits = self.st.bm25_search(query, top_k=top_k * 2)
        uris, texts, top_score = [], [], 0.0
        for obj, score in hits:
            doc = obj["uri"].split("/")[2] if obj["uri"].startswith("viking://") else ""
            if docs is not None and doc not in docs:
                continue                     # T4 能力边界：不越专科取证
            uris.append(obj["uri"])
            texts.append(f"[{obj['uri']}] {obj['text'][:300]}")
            top_score = max(top_score, score)
            if len(uris) >= top_k:
                break
        self.evidence_uris = uris
        return uris, "\n".join(texts), top_score

    def opine(self, patient: dict, query: str):
        pid = patient.get("patient_id", "?")
        if Guardrail.is_boundary_request(query):
            lvl, sc, why = confidence.score_confidence([], is_boundary=True)
            return {"role": self.role, "role_cn": ROLE_CN[self.role],
                    "answer": Guardrail.refuse(query), "citations": [],
                    "confidence": lvl, "conf_score": sc, "conf_reason": why,
                    "blocked": True}
        uris, ev_text, top_score = self.retrieve(query)
        docs = {u.split("/")[2] for u in uris}
        system = (f"你是ICU{ROLE_CN[self.role]}视角的循证助手。只依据给出的指南条款回答，"
                  f"聚焦：{ROLE_FOCUS[self.role]}。严禁诊断结论、治疗医嘱、预后判断。"
                  f"关键判断后用方括号标注证据 URI（如 [{uris[0] if uris else 'viking://...'}]）。")
        user = (f"【病例】{_patient_text(patient)}\n【指南条款】\n{ev_text or '（未取到条款）'}\n"
                f"【问题】{query}\n请给出{ROLE_CN[self.role]}视角的循证意见（100字内）。")
        raw = LLM.chat([{"role": "system", "content": system},
                        {"role": "user", "content": user}], max_tokens=400)
        if config.DISCLAIMER not in raw:
            raw += "\n" + config.DISCLAIMER
        gr = Guardrail.final_check(raw)
        lvl, sc, why = confidence.score_confidence(
            uris, bm25_top=top_score, multi_doc=len(docs) >= 2)
        return {"role": self.role, "role_cn": ROLE_CN[self.role], "answer": raw,
                "citations": uris, "confidence": lvl, "conf_score": sc,
                "conf_reason": why, "guardrail_ok": gr.ok,
                "guardrail_reason": gr.reasons()}


class ConsultationOrchestrator:
    """会诊编排器：按严重度动态组网，汇总多学科结论，异议留痕。"""

    def __init__(self, storage: Storage, audit=None):
        self.st = storage
        self.audit = audit
        self.trace: List[Dict] = []

    def _log(self, event, **kw):
        if self.audit:
            self.audit.log(event, **kw)

    def consult(self, patient: dict, query: str):
        sev = assess_severity(patient)
        if sev >= 4:
            path = ["resident", "pharmacist", "nurse", "attending"]
        elif sev >= 2:
            path = ["resident", "nurse", "attending"]
        else:
            path = ["resident", "attending"]
        self.trace.append({"event": "route", "severity": sev, "path": path})
        self._log("CONSULT_ROUTE", patient=patient.get("patient_id"),
                  severity=sev, path=">".join(path))

        opinions = []
        for role in path:
            op = SpecialistAgent(role, self.st).opine(patient, query)
            opinions.append(op)
            self.trace.append({"event": "opinion", "role": role,
                               "confidence": op["confidence"], "ncit": len(op["citations"])})
            self._log("CONSULT_OPINION", patient=patient.get("patient_id"),
                      role=role, confidence=op["confidence"], ncit=len(op["citations"]))

        disagreements = self._cross_check(opinions)
        consensus = self._consensus(patient, query, opinions, sev, disagreements)
        return {"severity": sev, "path": path, "opinions": opinions,
                "disagreements": disagreements, "consensus": consensus,
                "trace": self.trace}

    @staticmethod
    def _cross_check(opinions):
        levels = [o["confidence"] for o in opinions]
        dis = []
        if confidence.HIGH in levels and confidence.LOW in levels:
            dis.append({"type": "置信度分裂",
                        "detail": "专科间对证据强度判断不一致，建议人工复核", "levels": levels})
        for o in opinions:
            if not o.get("guardrail_ok", True):
                dis.append({"type": "护栏拦截", "role": o["role"],
                            "detail": o.get("guardrail_reason", "")})
        return dis

    def _consensus(self, patient, query, opinions, sev, disagreements):
        ops = "\n".join(f"【{o['role_cn']}·{o['confidence']}】{o['answer']}" for o in opinions)
        all_uris = [u for o in opinions for u in o["citations"]]
        docs = {u.split("/")[2] for u in all_uris}
        dis_txt = "；".join(d["type"] for d in disagreements) if disagreements else "无"
        system = ("你是ICU主治医师，综合各专科循证意见形成多学科评估结论。"
                  "严禁诊断/医嘱/预后，仅做证据归纳与指南定位，关键判断标注证据URI。")
        user = (f"病例:{_patient_text(patient)}\n严重度评分:{sev}\n问题:{query}\n"
                f"各专科意见:\n{ops}\n异议留痕:{dis_txt}\n"
                f"请给出多学科综合评估（150字内），指出哪些结论证据强、哪些需人工复核。")
        raw = LLM.chat([{"role": "system", "content": system},
                        {"role": "user", "content": user}], max_tokens=500)
        if config.DISCLAIMER not in raw:
            raw += "\n" + config.DISCLAIMER
        lvl, sc, why = confidence.score_confidence(all_uris, multi_doc=len(docs) >= 2)
        return {"answer": raw, "confidence": lvl, "conf_score": sc,
                "conf_reason": why, "citations": all_uris}
