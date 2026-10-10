"""DEMO3 多专科 Agent 会诊（临床缺口#2：单Agent vs 多角色协作）。
采用 T3 多专科动态组网（MANTA收敛版）+ T4 专科文档按需装载 + 交叉核验异议留痕。
演示：同一重症病例，对比"单Agent"与"多专科会诊"的评估完整性。
后端不可达时自动走 OfflineBrain 兜底，链路仍可完整演示。
"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from vikingrag.llm import LLM
from vikingrag.storage import Storage
from src.agents import ConsultationOrchestrator, SpecialistAgent, assess_severity
from src.audit import AuditLogger


def load_patient(pid):
    with open(os.path.join(config.PATIENT_DIR, f"{pid}.json"), encoding="utf-8") as f:
        return json.load(f)


def doc_dims(uris):
    """引用覆盖的指南文档维度数（viking://<doc>/... 的 <doc> 去重）。"""
    return len({u.split("/")[2] for u in uris if u.startswith("viking://")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", default="P003", help="病例ID（P003为重症休克）")
    ap.add_argument("--query", default="请依据指南对该患者做全面的多学科循证评估")
    args = ap.parse_args()

    print("=" * 64)
    print(f"DEMO3 多专科 Agent 会诊  病例={args.patient}")
    print("=" * 64)
    patient = load_patient(args.patient)
    sev = assess_severity(patient)
    print(f"\n病例: {patient['patient_id']} {patient['demographics']}")
    print(f"主诉: {patient['chief_complaint']}")
    print(f"严重度评分: {sev}  (>=4 走全路径:住院→药师→护理→主治)")
    print(f"会诊问题: {args.query}")
    print(f"LLM 通道: {LLM.backend}")

    storage = Storage(config.DB_PATH)
    audit = AuditLogger()

    # ---- 基线：单Agent（仅主治视角，无专科分工）----
    print("\n" + "-" * 64)
    print("【基线】单 Agent 评估（主治视角）")
    print("-" * 64)
    single = SpecialistAgent("attending", storage).opine(patient, args.query)
    print(f"置信度: {single['confidence']} ({single['conf_score']})  引用{len(single['citations'])}条")
    print(f"回答: {single['answer'][:250]}")
    single_dims = doc_dims(single["citations"])

    # ---- 三期：多专科会诊 ----
    print("\n" + "-" * 64)
    print("【三期】多专科动态会诊")
    print("-" * 64)
    orch = ConsultationOrchestrator(storage, audit=audit)
    result = orch.consult(patient, args.query)
    print(f"动态组网路径: {' → '.join(result['path'])}")
    for op in result["opinions"]:
        print(f"\n  ◆ {op['role_cn']}视角 [置信度 {op['confidence']} {op['conf_score']}] 引用{len(op['citations'])}条")
        print(f"    {op['answer'][:180]}")
    if result["disagreements"]:
        print("\n  ⚠ 异议留痕（防幻觉放大）:")
        for d in result["disagreements"]:
            print(f"    - {d['type']}: {d['detail']}")
    print("\n  【主治综合结论】")
    print(f"  置信度: {result['consensus']['confidence']} ({result['consensus']['conf_score']})")
    print(f"  {result['consensus']['answer'][:300]}")
    multi_dims = doc_dims(result["consensus"]["citations"])

    # ---- 对比 ----
    print("\n" + "-" * 64)
    print("完整性对比（核心验证指标）")
    print("-" * 64)
    print(f"  覆盖指南文档维度:  单Agent={single_dims}  多专科会诊={multi_dims}")
    print(f"  引用条款总数:      单Agent={len(single['citations'])}  多专科会诊={len(result['consensus']['citations'])}")
    print(f"  异议留痕条数:      单Agent=0  多专科会诊={len(result['disagreements'])}")

    audit.log("consultation", patient=args.patient, severity=sev,
              path=">".join(result["path"]), single_dims=single_dims,
              multi_dims=multi_dims, disagreements=len(result["disagreements"]))
    out = os.path.join(config.OUTPUT_DIR, f"poc3_consult_{args.patient}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"single": {k: single[k] for k in ("confidence", "conf_score", "answer", "citations")},
                   "consult": result}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n报告已保存: {out}")


if __name__ == "__main__":
    main()
