"""三期POC主调度入口
用法：
  python main_poc3.py            # 依次运行全部 DEMO
  python main_poc3.py --demo 2   # 只运行指定 DEMO
"""
import os, sys, subprocess, argparse

DEMOS = {
    1: "demo1_smoke.py",
    2: "demo2_course.py",
    3: "demo3_consult.py",
    4: "demo4_confidence.py",
    5: "demo5_durable.py",
}
DESC = {
    1: "冒烟自检（后端连通/知识库/各模块）",
    2: "长程病程跟踪（缺口#1：T1记忆分片+T2持久化+T5置信度）",
    3: "多专科Agent会诊（缺口#2：T3动态组网+T4按需装载）",
    4: "证据置信度分级（缺口#3：T5置信度量化与校准）",
    5: "Durable断点续跑实弹（T2崩溃恢复实证）",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", type=int, default=None, help="指定运行某个DEMO编号")
    ap.add_argument("--patient", default=None, help="透传给DEMO的病例ID")
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    which = [args.demo] if args.demo else sorted(DEMOS)
    for d in which:
        if d not in DEMOS:
            print(f"未知DEMO编号: {d}")
            continue
        cmd = [sys.executable, DEMOS[d]]
        if args.patient and d in (2, 3):
            cmd += ["--patient", args.patient]
        print(f"\n{'='*64}\n  运行 DEMO{d}：{DESC[d]}\n{'='*64}")
        subprocess.run(cmd, cwd=root)
    print("\n全部选定 DEMO 运行完毕，产物在 output/ 目录。")


if __name__ == "__main__":
    main()
