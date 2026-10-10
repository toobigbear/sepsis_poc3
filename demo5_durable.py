"""DEMO5 断点续跑实弹验证（T2 Durable 的"崩溃恢复"实证）。
模拟：长程评估跑到一半被"中断"（这里用只跑前2个窗来模拟），
再次运行自动从断点续跑，验证：已完成的窗不重跑、状态完整恢复、可回放。
这是图05 Durable"日志即状态、崩溃可恢复"在脓毒症长任务的直接落地。
后端不可达时自动走 OfflineBrain 兜底，链路仍可完整演示。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from vikingrag.llm import LLM
from vikingrag.storage import Storage
from src.course import CourseTracker
from src.durable import DurableSession


def _reset(pid):
    """清掉旧的会话/记忆文件，保证本演示可重复跑。"""
    for p in (os.path.join(config.SESSION_DIR, f"course_{pid}.sqlite3"),
              os.path.join(config.OUTPUT_DIR, "memory", f"{pid}_memory.json")):
        if os.path.exists(p):
            os.remove(p)


def main():
    pid = "T001"
    print("=" * 64)
    print("DEMO5 Durable 断点续跑实弹验证")
    print("=" * 64)
    print(f"LLM 通道: {LLM.backend}")
    with open(os.path.join(config.TIMELINE_DIR, f"{pid}.json"), encoding="utf-8") as f:
        full_patient = json.load(f)
    n_all = len(full_patient["timeline"])

    _reset(pid)
    storage = Storage(config.DB_PATH)
    tracker = CourseTracker(storage)

    # ---- 第一次：只跑前2个窗，模拟"中断" ----
    print("\n[第1次运行] 模拟中断：只评估前2个时间窗")
    partial = dict(full_patient)
    partial["timeline"] = full_patient["timeline"][:2]
    r1 = tracker.track(partial, resume=True, verbose=True)
    print(f"  第一次完成窗数: {r1['windows_evaluated']}  Durable事件数: {r1['durable_events']}")

    # ---- 第二次：跑全部时间窗，验证断点续跑 ----
    print(f"\n[第2次运行] 恢复完整任务：评估全部{n_all}个时间窗（前2窗应被跳过）")
    r2 = tracker.track(full_patient, resume=True, verbose=True)
    print(f"  第二次新评估窗数: {r2['windows_evaluated']}  Durable事件总数: {r2['durable_events']}")

    # ---- 回放：从事件日志重建完整病程 ----
    print("\n[回放] 从 Durable 事件日志重建完整病程")
    sess = DurableSession(f"course_{pid}")
    state = sess.recover()
    evals = [p for t, p in state["completed_steps"] if t == "timeline_eval"]
    print(f"  重放出 {len(evals)} 个时间窗评估:")
    for e in evals:
        print(f"    {e['t']} 置信度{e['confidence']} 乳酸{e['metrics']['lactate']} MAP{e['metrics']['map']}")
    sess.close()

    # ---- 验证结论 ----
    print("\n" + "-" * 64)
    print("断点续跑验证结论")
    print("-" * 64)
    dup_ok = r2["windows_evaluated"] == n_all - 2   # 第二次只新评了后面的窗
    replay_ok = len(evals) == n_all                 # 回放能重建全部窗
    print(f"  断点去重（已完成窗不重跑）: {'✓' if dup_ok else '✗'}")
    print(f"  事件日志可完整回放病程:     {'✓' if replay_ok else '✗'}")
    print("\n  意义：ICU长程监护（小时级）中推理中断不丢病程，可从断点无缝续跑并全程回放。")


if __name__ == "__main__":
    main()
