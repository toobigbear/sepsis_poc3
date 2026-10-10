# -*- coding: utf-8 -*-
"""时序病程跟踪编排器（D1 核心，适配二期地基）。

串起 T1记忆分片 + T2 Durable断点续跑 + 二期Storage取证 + T5置信度。
每个时间窗作为独立"子Agent评估"：
1. T2 Durable：先查该窗是否已评估（断点续跑去重），评估后原子写入事件；
2. T1 记忆：评估时只带"滚动摘要"作为上下文（分片省内存），评估后写回摘要；
3. 取证：二期 Storage.bm25_search（viking:// URI），按本窗异常指标触发；
4. T5 置信度：基于实际 Read 的 viking URI 信号打分。
全程写审计；记录"上下文峰值"对比"全量灌入"基线（演示分片省内存）。
"""
from __future__ import annotations

import re
from typing import Dict, List

import config
from vikingrag.llm import LLM, approx_tokens
from vikingrag.storage import Storage
from src.guardrails import Guardrail
from src import confidence
from src.memory import CourseMemory
from src.durable import DurableSession


def _num(text, pattern):
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


def _step_text(step: dict) -> str:
    vitals = "；".join(f"{k} {v}" for k, v in step.get("vitals", {}).items())
    labs = "；".join(f"{k} {v}" for k, v in step.get("labs", {}).items())
    return f"生命体征:{vitals} 化验:{labs} 血管活性:{step.get('vasopressor')} 机械通气:{step.get('mv')}"


def _step_metrics(step: dict) -> Dict[str, float]:
    text = _step_text(step)
    return {
        "lactate": _num(text, r"乳酸[^\d]{0,4}(\d+\.?\d*)") or 0.0,
        "map": _num(text, r"MAP\s*(\d+\.?\d*)") or _num(text, r"(\d+)/\d+\s*mmHg") or 0.0,
        "creatinine": _num(text, r"肌酐[^\d]{0,4}(\d+\.?\d*)") or 0.0,
    }


def _window_queries(metrics: Dict[str, float], step: dict) -> List[str]:
    """按本窗异常指标触发取证查询（子Agent取证范围=分片）。"""
    qs = []
    if metrics["lactate"] > 2:
        qs.append("乳酸 液体复苏 血管活性 集束化")
    if metrics["map"] and metrics["map"] < 65:
        qs.append("平均动脉压 去甲肾上腺素 脓毒性休克")
    if metrics["creatinine"] > 170:
        qs.append("肾脏 肌酐 急性肾损伤 SOFA")
    text = _step_text(step)
    pf = _num(text, r"PaO2/FiO2[^\d]{0,4}(\d+\.?\d*)")
    if pf and pf < 300:
        qs.append("呼吸 ARDS 氧合 保护性通气")
    plt = _num(text, r"血小板[^\d]{0,4}(\d+\.?\d*)")
    if plt and plt < 100:
        qs.append("凝血 血小板 SOFA")
    if not qs:
        qs.append("脓毒症 定义 器官功能障碍 SOFA")
    return qs[:2]


class CourseTracker:
    """对单个时序病例做长程病程跟踪。"""

    def __init__(self, storage: Storage, audit=None):
        self.st = storage
        self.audit = audit

    def _log(self, event, **kw):
        if self.audit:
            self.audit.log(event, **kw)

    def _retrieve(self, queries, top_k=4):
        uris, texts, top = [], [], 0.0
        for q in queries:
            for obj, score in self.st.bm25_search(q, top_k=top_k):
                if obj["uri"] in uris:
                    continue
                uris.append(obj["uri"])
                texts.append(f"[{obj['uri']}] {obj['text'][:280]}")
                top = max(top, score)
            if len(uris) >= top_k:
                break
        return uris[:top_k], "\n".join(texts[:top_k]), top

    def track(self, patient: dict, resume: bool = True, verbose: bool = True):
        pid = patient["patient_id"]
        mem = CourseMemory(pid)
        sess = DurableSession(f"course_{pid}")
        done = sess.done_steps("timeline_eval") if resume else set()
        windows = patient["timeline"]
        results = []
        full_total = shard_total = 0

        for i, step in enumerate(windows):
            t_label, step_id = step["t"], f"{pid}_{i}"
            if step_id in done:
                if verbose:
                    print(f"  [续跑] {t_label} 已完成，跳过")
                continue
            full_total += approx_tokens(str(windows[:i + 1]))
            shard_total += mem.context_size_estimate() // 2 + approx_tokens(_step_text(step))

            metrics = _step_metrics(step)
            queries = _window_queries(metrics, step)
            uris, ev_text, top = self._retrieve(queries)
            mem_ctx = mem.context_for_next()
            docs = {u.split("/")[2] for u in uris}

            system = ("你是ICU循证助手，评估单个时间窗的病情变化趋势。只依据指南条款，"
                      "严禁诊断/医嘱/预后，描述趋势并标注证据URI。")
            user = (f"【病程记忆摘要】{mem_ctx['rolling_summary'] or '（首个时间窗）'}\n"
                    f"【未完成关注】{mem_ctx['open_concerns']}\n"
                    f"【本时间窗】{t_label} {step['desc']}\n{_step_text(step)}\n"
                    f"【指南条款】\n{ev_text or '（未取到）'}\n"
                    f"请评估本窗病情变化趋势（乳酸/MAP/器官功能），80字内。")
            raw = LLM.chat([{"role": "system", "content": system},
                            {"role": "user", "content": user}], max_tokens=350)
            if config.DISCLAIMER not in raw:
                raw += "\n" + config.DISCLAIMER
            gr = Guardrail.final_check(raw)
            lvl, sc, why = confidence.score_confidence(
                uris, bm25_top=top, multi_doc=len(docs) >= 2)

            concerns = []
            if metrics["map"] and metrics["map"] < 65:
                concerns.append("循环未达标")
            if metrics["creatinine"] > 200:
                concerns.append("肾功能恶化")
            summary = f"{t_label}:{step['desc']}(乳酸{metrics['lactate']},MAP{metrics['map']})"
            mem.add_step(t_label, summary, metrics, concerns=concerns)

            sess.append("timeline_eval", {
                "step_id": step_id, "t": t_label, "desc": step["desc"],
                "assessment": raw, "confidence": lvl, "conf_score": sc,
                "metrics": metrics, "citations": uris})
            self._log("TIMELINE_EVAL", patient=pid, t=t_label, confidence=lvl,
                      shard=shard_total, full=full_total)

            results.append({"t": t_label, "desc": step["desc"], "assessment": raw,
                            "confidence": lvl, "conf_score": sc, "citations": uris,
                            "guardrail_ok": gr.ok, "metrics": metrics})
            if verbose:
                print(f"  [完成] {t_label} 置信度={lvl}({sc}) 引用{len(uris)}条")

        saved = full_total - shard_total
        pct = round(saved / full_total * 100, 1) if full_total else 0
        report = {"patient_id": pid, "name": patient.get("chief_complaint", ""),
                  "windows_evaluated": len(results), "results": results,
                  "memory_state": mem.state,
                  "lactate_trend": mem.trend_of("lactate"),
                  "map_trend": mem.trend_of("map"),
                  "context_compare": {"full_total": full_total, "shard_total": shard_total,
                                      "saved": saved, "saving_pct": pct},
                  "durable_session": sess.path, "durable_events": sess.count()}
        sess.close()
        return report
