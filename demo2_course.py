"""DEMO2 长程病程跟踪（临床缺口#1：单轮问答 vs 长程病程）。
采用 T1持久记忆分片 + T2 Durable断点续跑 + T5置信度。
演示：6小时时序病例逐时间窗评估，全程可续跑、可回放，并量化"分片省内存"。
后端不可达时自动走 OfflineBrain 兜底，链路仍可完整演示。
"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from vikingrag.llm import LLM
from vikingrag.storage import Storage
from src.course import CourseTracker
from src.audit import AuditLogger


def load_timeline(pid):
    path = os.path.join(config.TIMELINE_DIR, f"{pid}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", default="T001", help="时序病例ID (T001/T002)")
    ap.add_argument("--no-resume", action="store_true", help="禁用断点续跑(从头评估)")
    args = ap.parse_args()

    print("=" * 64)
    print(f"DEMO2 长程病程跟踪  病例={args.patient}  续跑={'关' if args.no_resume else '开'}")
    print("=" * 64)
    patient = load_timeline(args.patient)
    print(f"\n病例: {patient['patient_id']} {patient['demographics']}")
    print(f"主诉: {patient['chief_complaint']}")
    print(f"基线SOFA={patient['baseline_sofa']}  时间窗数={len(patient['timeline'])}")
    print(f"LLM 通道: {LLM.backend}")

    storage = Storage(config.DB_PATH)
    tracker = CourseTracker(storage, audit=AuditLogger())
    report = tracker.track(patient, resume=not args.no_resume, verbose=True)

    print("\n" + "-" * 64)
    print("病程跟踪结果汇总")
    print("-" * 64)
    for r in report["results"]:
        print(f"\n◆ {r['t']} {r['desc']}  [置信度 {r['confidence']} {r['conf_score']}]")
        print(f"  {r['assessment'][:200]}")
        if r["citations"]:
            print(f"  引用: {', '.join(r['citations'][:3])}")

    print("\n" + "-" * 64)
    print("关键指标趋势（T1 持久记忆）")
    print("-" * 64)
    print(f"  乳酸趋势: {report['lactate_trend']}")
    print(f"  MAP趋势 : {report['map_trend']}")

    cc = report["context_compare"]
    print("\n" + "-" * 64)
    print("上下文分片省内存对比（T1 核心验证指标）")
    print("-" * 64)
    print(f"  若全量灌入累计上下文 ≈ {cc['full_total']} tokens")
    print(f"  三期分片后实际上下文 ≈ {cc['shard_total']} tokens")
    print(f"  节省 ≈ {cc['saved']} tokens（{cc['saving_pct']}%）")
    print(f"\n  Durable会话库: {report['durable_session']}  事件数={report['durable_events']}")

    out = os.path.join(config.OUTPUT_DIR, f"poc3_course_{args.patient}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {out}")
    print("提示：再次运行同一病例可演示断点续跑（已完成的窗会跳过）。")


if __name__ == "__main__":
    main()
