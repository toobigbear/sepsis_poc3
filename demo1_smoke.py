"""DEMO1 冒烟测试：验证 LLM 后端连通 + 知识库加载 + 各三期模块可导入可用。
不消耗多少 token，用于跑正式 DEMO 前的环境自检。
后端不可达时自动走 OfflineBrain 兜底，本地模块仍可全部验证。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from vikingrag.llm import LLM
from vikingrag.storage import Storage
from src.guardrails import Guardrail
from src.durable import DurableSession
from src.memory import CourseMemory
from src import confidence


def main():
    print("=" * 60)
    print("DEMO1 冒烟自检（三期）")
    print("=" * 60)

    print(f"\n[1] LLM 后端（三级降级链：LM Studio -> Ollama -> OfflineBrain）")
    print(f"    当前通道: {LLM.backend}  模型: {LLM.model}")
    probe = LLM.chat([{"role": "user", "content": "用一句话回答：脓毒症的核心病理环节是什么？"}],
                     max_tokens=60)
    print(f"    试答: {probe[:80].replace(chr(10), ' ')}")

    print("\n[2] 知识库（二期 VikingRAG 层次化存储 + BM25）")
    st = Storage(config.DB_PATH)
    n_docs = st.conn.execute("SELECT COUNT(*) n FROM nodes WHERE kind='doc'").fetchone()["n"]
    n_objs = st.conn.execute("SELECT COUNT(*) n FROM objects").fetchone()["n"]
    print(f"    已入库 {n_docs} 份指南 / {n_objs} 个对象  (库: {os.path.basename(config.DB_PATH)})")
    hits = st.bm25_search("乳酸 液体复苏 集束化", top_k=2)
    print(f"    检索测试 '乳酸 液体复苏 集束化' -> 命中 {len(hits)} 条:")
    for obj, score in hits:
        print(f"      {obj['uri']}  (BM25={score:.2f})")
    uris = [obj["uri"] for obj, _ in hits]
    top_score = hits[0][1] if hits else 0.0

    print("\n[3] 护栏（二期三层防线）")
    b1 = Guardrail.is_boundary_request("帮我开个处方，再判断下预后还能活多久")
    b2 = Guardrail.is_boundary_request("乳酸升高提示什么？")
    print(f"    越界请求识别: {'✓ 拦截' if b1 else '✗'}")
    print(f"    正常问题放行: {'✓' if not b2 else '✗'}")

    print("\n[4] T2 Durable 会话（写->模拟崩溃->重放恢复）")
    sid = "smoke_test"
    path = os.path.join(config.SESSION_DIR, f"{sid}.sqlite3")
    if os.path.exists(path):
        os.remove(path)
    s = DurableSession(sid)
    s.append("test", {"step_id": "x1", "val": 42})
    s.close()
    s2 = DurableSession(sid)   # 重新打开同一文件 = 崩溃后恢复
    st_state = s2.recover()
    print(f"    写入1条事件后重开重放: 事件数={s2.count()} 已恢复步骤={len(st_state['completed_steps'])}")
    s2.close()
    os.remove(path)

    print("\n[5] T1 病程持久记忆（滚动摘要 + 趋势）")
    m = CourseMemory("smoke")
    m.add_step("T0", "入院(乳酸4.2)", {"lactate": 4.2, "map": 64}, concerns=["循环未达标"])
    m.add_step("T1", "复苏后(乳酸3.4)", {"lactate": 3.4, "map": 70}, concerns=[])
    print(f"    乳酸趋势: {m.trend_of('lactate')}  记忆上下文≈{m.context_size_estimate()}字符")
    os.remove(m.path)

    print("\n[6] T5 证据置信度量化")
    lvl, sc, why = confidence.score_confidence(uris, bm25_top=top_score, multi_doc=True)
    print(f"    实取证据置信度: {lvl} ({sc}) - {why}")
    lvlb, _, _ = confidence.score_confidence([], is_boundary=True)
    print(f"    边界问题置信度(应LOW): {lvlb}")

    print("\n" + "=" * 60)
    print(f"冒烟完成。LLM 通道={LLM.backend}"
          + ("（离线兜底：链路可演示，起 LM Studio/Ollama 后自动用真模型）"
             if LLM.backend == "offline" else "（在线）"))
    print("=" * 60)


if __name__ == "__main__":
    main()
