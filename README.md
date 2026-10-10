# ICU 脓毒症智能证据助手 · POC 三期工程

> 定位跃迁：从"取证问答"到"临床决策协作"。
> 在二期"取证优先、质控贯穿、复盘闭环"骨架上，补三个临床缺口，
> 采用六个前沿技术模块（已按"易于实现、医院可复现"收敛）。
> **本工程为完全虚构模拟数据的科研预研原型，不构成任何诊疗依据。**

---

## 一、三期补的三个临床缺口

| 临床缺口 | 二期现状 | 三期方案 | 对应DEMO |
|---|---|---|---|
| 单轮问答 vs 长程病程 | 只评单时间点 | T1持久记忆分片 + T2 Durable断点续跑 | DEMO2 / DEMO5 |
| 单Agent vs 多角色协作 | 单Agent翻指南 | T3多专科动态组网 + T4 专科文档按需装载 | DEMO3 |
| 事后审计 vs 过程可信 | 有日志无置信度 | T5证据置信度量化与校准 | DEMO4 |

## 二、六个前沿技术模块（取舍后）

| 模块 | 来源 | 三期实现 | 取舍说明 |
|---|---|---|---|
| T1 持久记忆+KV分片 | 图A2论文(UCLA 2026.10) | `src/memory.py` 滚动摘要+趋势，每窗只带摘要上下文 | 只用于跨会话病程（论文证伪单题场景，已避开） |
| T2 Durable崩溃恢复 | 图05 Pi手册 | `src/durable.py` SQLite事件溯源，断点续跑+Fork+回放 | 完整实现，医疗长任务刚需 |
| T3 多Agent拓扑 | 图A5 MANTA(Cornell 2026.07) | `src/agents.py` 4固定角色+按严重度动态组网 | **收敛**：不做全拓扑进化，保可解释性 |
| T4 Skills三开关 | 图A4 LangChain(2026.10) | `src/agents.py` ROLE_DOCS：每个专科只在本专科指南文档内取证 | **收敛**：专科文档集合=能力边界，不激活不进上下文 |
| T5 置信度量化 | 图01/18 Anthropic | `src/confidence.py` 基于实取证据信号打分+校准 | 解决"临床不敢用"核心痛点 |
| T6 SGLang前缀复用 | 图A1 | **本期略** | 需GPU服务器，POC单病例收益有限，留待院内GPU部署 |

> T6 说明：本地单机 POC 阶段用 LM Studio/Ollama 即可，SGLang 的多Agent前缀复用收益要在院内 GPU 服务器+并发场景才能体现，故本期不实现，已在策划文档标注为后续项。

## 三、与二期工程的复用关系

三期**完整复用二期已验证的地基**，只做增量、不改二期约定：

| 二期地基（原样保留） | 三期增量（新增模块） |
|---|---|
| `vikingrag/` 检索存储全栈（BM25、`viking://` URI、经验边） | `src/memory.py`（T1） |
| `vikingrag/llm.py` 三级降级链 + OfflineBrain 兜底 | `src/durable.py`（T2） |
| `src/guardrails.py` 三层护栏（红线冻结） | `src/agents.py`（T3+T4） |
| `src/audit.py` JSONL 全轨迹审计 | `src/confidence.py`（T5） |
| `data/kb` 8份指南 / `data/patients` 4病例 / `data/qa` 25题评测集 | `src/course.py`（时序编排）+ `data/patients_timeline` 2个时序病例 |

## 四、环境与安装（无 Docker/WSL，与二期一致）

**要求**：Windows + Python 3.10 + PyCharm（你已有）+ 本地 LLM 后端（可选）。

1. **安装依赖**（只需 openai 一个第三方库）：
   ```bash
   pip install -r requirements.txt
   ```
2. **建库**（首次运行必须执行，把8份指南索引进 SQLite）：
   ```bash
   python ingest.py
   ```
3. **启动本地 LLM 后端**（可选，与二期相同的三级降级链）：
   - **LM Studio**（主通道）：加载模型并开启本地服务，默认 `http://localhost:1234/v1`
   - **Ollama**（兜底通道）：`ollama serve`，OpenAI 兼容端点 `http://localhost:11434/v1`
   - **都不启动也能跑**：自动降级到 OfflineBrain 规则引擎，全链路仍可演示（评测类DEMO建议起后端）
4. **环境变量**（按需，都有默认值）：
   ```bash
   # PowerShell 示例
   $env:POC_MODEL="qwen3-8b"              # 模型槽位（config.py MODEL_SLOTS）
   $env:LMSTUDIO_MODEL="qwen3-8b"         # 与服务端实际加载的模型标识一致
   $env:LMSTUDIO_BASE_URL="http://localhost:1234/v1"
   $env:OLLAMA_BASE_URL="http://localhost:11434/v1"
   ```

## 五、运行（5个DEMO）

```bash
# 一键依次运行全部
python main_poc3.py

# 或单独运行
python demo1_smoke.py        # 冒烟自检：先跑这个确认环境OK
python demo2_course.py       # 长程病程跟踪（缺口#1）
python demo2_course.py --patient T002   # 换"复苏反应良好"病例
python demo3_consult.py      # 多专科会诊（缺口#2，默认重症P003）
python demo3_consult.py --patient P001  # 换病例
python demo4_confidence.py   # 置信度分级与校准（缺口#3）
python demo5_durable.py      # Durable断点续跑实弹
```

**强烈建议的运行顺序**：先 `ingest.py` 建库，再 `demo1_smoke.py` 自检，然后依次 2→3→4→5。

## 六、每个DEMO验证什么

- **DEMO1 冒烟**：LLM 降级链、8份指南入库检索、护栏、Durable、记忆、置信度全模块自检。
- **DEMO2 病程跟踪**：6小时4个时间窗逐窗评估，输出乳酸/MAP趋势，并**量化"分片省内存"**（对比"全量灌入"的上下文）。再跑一次可演示断点续跑（已完成窗跳过）。
- **DEMO3 多专科会诊**：同一重症病例，对比"单Agent"vs"多专科会诊"的**覆盖指南维度数、引用条款数、异议留痕条数**。动态组网路径按严重度自动选择。
- **DEMO4 置信度**：复用二期25题评测集（含3道红线题），输出**置信度校准一致率**——红线题能否正确降级 LOW，取到金牌证据的题能否给出 MEDIUM/HIGH。这是"敢交付"的关键证据。
- **DEMO5 断点续跑**：模拟"跑一半中断→恢复"，验证已完成窗不重跑、事件日志可完整回放病程。

## 七、目录结构

```
sepsis_poc3/
├── config.py              # 配置：模型槽位/降级链/Harness参数/路径（与二期同约定）
├── ingest.py              # 知识库建库脚本（二期原样）
├── main_poc3.py           # 主调度（参考二期 main_poc.py 风格）
├── requirements.txt       # 仅 openai
├── demo1_smoke.py         # 冒烟自检
├── demo2_course.py        # DEMO2 长程病程（缺口#1）
├── demo3_consult.py       # DEMO3 多专科会诊（缺口#2）
├── demo4_confidence.py    # DEMO4 置信度分级（缺口#3）
├── demo5_durable.py       # DEMO5 断点续跑实弹
├── src/
│   ├── memory.py          # T1 病程持久记忆（滚动摘要+趋势）
│   ├── durable.py         # T2 Durable会话（SQLite事件溯源/续跑/Fork/回放）
│   ├── agents.py          # T3 多专科动态组网 + T4 专科文档能力边界
│   ├── confidence.py      # T5 证据置信度量化与校准
│   ├── course.py          # 时序病程编排器（串起T1+T2+T5）
│   ├── guardrails.py      # 三层护栏（二期原样）
│   └── audit.py           # JSONL全轨迹审计（二期原样）
├── vikingrag/             # 二期检索存储全栈（原样）
│   ├── llm.py             # 三级降级链 + OfflineBrain 兜底
│   ├── storage.py         # 层次化语义存储 + BM25（viking:// URI）
│   ├── tools.py           # Search/List/Grep/Read 工具集
│   ├── retriever.py       # 证据缺口多轮检索
│   ├── experience.py      # 经验边复用（VikingRAG-E+）
│   └── prompts.py         # 提示词模板
├── data/
│   ├── kb/                # 8份指南（与二期一致）
│   ├── patients/          # P001-P004 单时点模拟病例（与二期一致）
│   ├── patients_timeline/ # T001/T002 6小时时序模拟病例（三期新增）
│   └── qa/qa_set.json     # 25题评测集（含3道红线题，与二期一致）
└── output/                # 运行产物：报告JSON、Durable会话库、记忆、审计JSONL
```

## 八、安全红线（冻结，贯穿所有模块）

AI不出诊断 / 不出具体医嘱 / 不做预后；数据不出院本地离线运行；
全部输出附免责声明；每条结论可追溯指南原文（`viking://` URI）。
所有病例、指南条款均为**完全虚构的模拟示例**，仅用于POC验证。

## 九、常见问题

- **检索命中为0**：先确认已运行 `python ingest.py` 建库（生成 `viking_kb.sqlite3`）。
- **回答显示"离线降级"**：LM Studio/Ollama 未启动。不影响链路演示；要真实生成质量，启动任一后端后重跑即可（自动回升，无需改代码）。
- **想换模型**：改环境变量 `POC_MODEL` / `LMSTUDIO_MODEL` 即可，代码无需改动。
- **断点续跑想重来**：删除 `output/sessions/course_T001.sqlite3` 与 `output/memory/T001_memory.json` 即可从头评估（DEMO5 每次运行会自动重置）。
- **置信度全是LOW**：多因未建库或未起后端，先跑 demo1 自检逐项确认。
