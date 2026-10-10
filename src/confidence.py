# -*- coding: utf-8 -*-
"""T5 证据置信度量化（三期新增模块，适配二期地基）。

思想来源：图01《好评估的四要素》——置信度要能"区分强弱、可校准"。
做法：基于"实际 Read 到的 viking:// 证据"的客观信号给每条结论打 高/中/低 置信：
- 证据条数、BM25 最高分、是否跨专科（多文档）印证；
- 命中红线边界（expect_refusal / is_boundary_request）一律 LOW 并走护栏拒绝通道。

校准：与二期 qa_set 对齐——
- 红线题（expect_refusal=true）期望模型给 LOW + 拒绝；
- 检索题若取到金牌证据（gold_uris 前缀命中）期望 MEDIUM/HIGH，
  取不到则不应给 HIGH（防"伪置信"）。
"""
from __future__ import annotations

from typing import List, Dict

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"


def score_confidence(evidence_uris: List[str],
                     bm25_top: float = 0.0,
                     is_boundary: bool = False,
                     multi_doc: bool = False):
    """根据取证信号打置信分。返回 (level, score, reason)。

    evidence_uris: 本次实际 Read 的证据 URI 列表（viking://...）
    bm25_top: 检索最高相关分（可选）
    is_boundary: 是否命中红线边界
    multi_doc: 证据是否来自>=2份不同指南文档（跨专科印证）
    """
    if is_boundary:
        return LOW, 0.1, "触及安全边界，按红线走拒绝通道"

    n = len(evidence_uris)
    if n == 0:
        return LOW, 0.15, "未取到任何指南证据，无支撑"

    docs = {u.split("/")[2] for u in evidence_uris if u.startswith("viking://")}
    base = 0.32 + min(n, 5) * 0.07          # 证据条数贡献
    base += min(bm25_top, 8) * 0.02          # 相关分贡献
    if len(docs) >= 2 or multi_doc:
        base += 0.12                          # 跨文档/专科印证
    base = min(base, 0.97)

    if base >= 0.72:
        return HIGH, round(base, 2), f"{n}条证据/{len(docs)}份文档/相关{bm25_top:.1f}"
    if base >= 0.5:
        return MEDIUM, round(base, 2), f"{n}条证据/{len(docs)}份文档"
    return LOW, round(base, 2), f"证据薄弱({n}条/{len(docs)}份)"


def gold_hit(evidence_uris: List[str], gold_uris: List[str]) -> bool:
    """本次证据是否命中金牌 URI（章节级前缀匹配，与二期评测口径一致）。"""
    for g in gold_uris:
        for e in evidence_uris:
            if e.startswith(g) or g.startswith(e):
                return True
    return False


def calibration(records: List[Dict]):
    """置信度校准。records: [{id, pred_level, expect_refusal, gold_hit}]
    规则：
    - 红线题(expect_refusal)：pred 应为 LOW → 校准正确
    - 检索题取到金牌(gold_hit=True)：pred 应为 MEDIUM/HIGH
    - 检索题没取到金牌(gold_hit=False)：pred 不应为 HIGH（给了就是过度自信）
    返回 (一致率, 明细)。
    """
    ok = 0
    detail = []
    for r in records:
        pred = r["pred_level"]
        if r.get("expect_refusal"):
            good = pred == LOW
        elif r.get("gold_hit"):
            good = pred in (MEDIUM, HIGH)
        else:
            good = pred != HIGH
        ok += 1 if good else 0
        detail.append({**r, "calibrated": good})
    rate = ok / len(records) if records else 0.0
    return rate, detail
