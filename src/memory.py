"""T1 持久记忆层 + KV 分片（跨会话病程跟踪专用）。

思想来源：图A2 论文——把长上下文推理拆给多个子Agent，使每次调用的
活跃上下文只由"本次所需"界定；持久记忆只在"跨会话需累计"场景有效。

重要设计取舍（尊重论文证伪结论）：
- 本模块只服务于"跨时间窗的病程跟踪"（持久记忆真正有效的场景），
  绝不用于"单题指南问答"（论文已证伪其收益）。
- 每个时间窗独立取证（子Agent），只把"结构化病程摘要"写入持久记忆，
  主Agent汇总时只读摘要而非全部原始数据 → 控制上下文峰值。

记忆结构：rolling summary（滚动摘要），每个时间窗评估后压缩追加，
  并保留关键决策与未完成关注点（绝不压缩掉的清单）。
"""
import json
import os
import config


class CourseMemory:
    """单患者病程持久记忆：滚动摘要 + 关键决策清单。"""

    def __init__(self, patient_id, memory_dir=None):
        self.patient_id = patient_id
        self.memory_dir = memory_dir or os.path.join(config.OUTPUT_DIR, "memory")
        os.makedirs(self.memory_dir, exist_ok=True)
        self.path = os.path.join(self.memory_dir, f"{patient_id}_memory.json")
        self.state = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        return {"patient_id": self.patient_id, "rolling_summary": "",
                "key_decisions": [],        # 关键决策（绝不压缩）
                "open_concerns": [],        # 未完成关注点（绝不压缩）
                "trend": {},                # 指标趋势 {metric: [val,...]}
                "steps": []}                # 已处理时间窗

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def add_step(self, t_label, summary, metrics=None, decisions=None, concerns=None):
        """追加一个时间窗的结构化摘要（而非原始数据）。"""
        self.state["steps"].append(t_label)
        if summary:
            prev = self.state["rolling_summary"]
            self.state["rolling_summary"] = (prev + " | " + summary).strip(" |")
        if metrics:
            for k, v in metrics.items():
                self.state["trend"].setdefault(k, []).append(v)
        if decisions:
            self.state["key_decisions"].extend(decisions)
        if concerns:
            self.state["open_concerns"] = concerns   # 滚动更新未完成关注
        self.save()

    def trend_of(self, metric):
        return self.state["trend"].get(metric, [])

    def context_for_next(self):
        """给下一时间窗子Agent的精简上下文（摘要而非全部历史）。"""
        return {
            "rolling_summary": self.state["rolling_summary"],
            "key_decisions": self.state["key_decisions"],
            "open_concerns": self.state["open_concerns"],
            "lactate_trend": self.trend_of("lactate"),
            "map_trend": self.trend_of("map"),
        }

    def context_size_estimate(self):
        """记忆上下文大小（字符），用于演示"分片省内存"的对比。"""
        return len(json.dumps(self.context_for_next(), ensure_ascii=False))
