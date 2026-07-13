# Prompt 与模板治理（A/B 实验版）设计

- 日期：2026-07-13
- 状态：已评审，待实现
- 范围：`apps/luna-corpus`

## 1. 背景与目标

当前 RAG 主问答等提示词以硬编码字符串/常量散落在多处（`services/prompt_builder.py`、`services/llm.py`、`agent/modes/*`、`quality/judge.py`），中英文混杂、无版本、无法在不发版的情况下调整，也无法对比不同 prompt 的效果。

本设计把 **RAG 主问答提示词**收敛为可管理资产，实现完整的 A/B 实验闭环，并与既有质量评估模块联动做显著性检验。

**目标（D 档：可实验 + A/B + 与质量评估联动）**：
- 集中化：Prompt 从硬编码收敛为「文件保底 + 数据库实验版本」的混合存储。
- 可实验：按知识库配置 A/B 实验，稳定哈希分流，埋点记录每次问答命中的版本。
- 可判定：复用 `QAInteraction`/`QAEvaluation`/`QAFeedback`，按版本聚合并对每个指标独立做显著性检验。

**本期范围（聚焦）**：仅治理 RAG 主问答提示词（`prompt_builder.py` 的中英文版）。Agent 各模式（direct/react/plan_execute/langgraph）与 `judge.py` 评审提示词**不纳入本期**——judge 是「打分尺子」，纳入 A/B 会破坏效果对比基准。跑通样板后再按同一机制扩展。

## 2. 关键决策记录

| 维度 | 决策 |
|---|---|
| 治理目标档位 | D：可实验 + A/B + 质量评估联动 |
| 治理范围 | 仅 RAG 主问答提示词 |
| 存储方式 | C：混合——文件默认保底 + 数据库实验版本 |
| 分流粒度 | 按知识库（knowledge_base）配置实验 |
| 分流策略 | 稳定哈希（可复现、带会话粘性） |
| 结果判定 | 聚合 + 自动显著性检验 |
| 显著性呈现 | 每指标独立报告 p 值/方向，不做加权黑箱 |
| 统计实现 | 纯 Python 标准库（项目无 numpy/scipy，刻意保持依赖精简） |
| 架构落点 | 新建 `app/prompts/` 模块 |

## 3. 模块结构与职责边界

```
app/prompts/
├── __init__.py
├── registry.py      # 模板加载：文件默认层 + DB 覆盖层，带内存缓存
├── templates/       # 文件保底模板（YAML），version 字段、中英文
│   └── rag_qa.yaml
├── experiment.py    # 按知识库读实验配置 + 稳定哈希分流 → 选定版本
├── stats.py         # Welch's t-test + 双比例 z-test（纯标准库）
└── schemas.py       # Pydantic 模型（模板、实验配置、分流结果、统计结论）
```

**职责边界**：
- `registry`：只管「给定 key + 版本，返回模板文本」，不懂实验；负责文件默认层与 DB 覆盖层的合并、缓存与失效。
- `experiment`：只管「给定知识库 + prompt_key + 分流种子，返回该用哪个版本 ID」，调用 registry 取文本。
- `stats`：纯函数库，输入两组样本，输出 p 值/均值差/置信区间，不碰 DB/IO。
- `schemas`：模块内外交互的 Pydantic 结构。
- `services/prompt_builder.py`（保留原位）：改为调用 `experiment` 选版本 → `registry` 取模板文本 → 填入 question/context/history。**渲染逻辑与选择逻辑解耦。**

`prompts` 模块与 `quality` 模块通过 `QAInteraction.prompt_version_id` 这一 ID 松耦合：`prompts` 负责写入版本 ID，`quality`/report 负责按版本聚合。

## 4. 数据模型

新增 2 张表，与现有表零耦合（仅通过 ID 关联）。

### 4.1 `prompt_versions` — Prompt 版本资产

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str PK | |
| prompt_key | str | 逻辑标识，如 `rag_qa` |
| version_label | str | 人类可读版本名，如 `v2-concise` |
| lang | str | `zh` / `en` |
| template_text | text | 带占位符的模板正文 |
| status | enum | `draft` / `active` / `archived` |
| source | enum | `file`（文件同步来的保底）/ `db`（运营新建） |
| knowledge_base_id | str nullable | null=全局可用；否则限定该知识库 |
| created_at | datetime | |

### 4.2 `prompt_experiments` — 按知识库的实验配置

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str PK | |
| knowledge_base_id | str | 实验归属知识库 |
| prompt_key | str | 实验针对哪个 prompt |
| status | enum | `running` / `stopped` |
| variants | JSON | `[{version_id, weight}]` 配比，如 `[{A,50},{B,50}]` |
| created_at | datetime | |

### 4.3 现有表改动

`QAInteraction` 新增一列 `prompt_version_id str nullable`——记录本次问答实际命中的版本。这是「标记 → 按版本聚合对比」的关键连接点。

### 4.4 保底规则

- 文件模板同步进 `prompt_versions`（source=`file`），保证 DB 空时也有 active 版本可用。
- 实验未配置 / 已 `stopped` 时，直接用该 `prompt_key`+`lang` 的 file 默认 active 版本。

## 5. 运行时数据流

在 `rag_graph.py` 现调用 `build_rag_prompt` 的位置：

```
1. 请求带 knowledge_base_id + lang + 分流种子(conversation_id 或新生成)
2. experiment.select_version(kb_id, "rag_qa", lang, seed):
   ├─ 查 prompt_experiments：该 kb 有 running 实验？
   │   ├─ 有 → stable_hash(seed) % 100 落在哪个 variant 区间 → 选中 version_id
   │   └─ 无 → 取 file 默认 active 版本 version_id
   └─ 返回 (version_id, template_text)   ← registry 提供文本，带缓存
3. prompt_builder 用 template_text 渲染 question/context/history
4. LLM 生成回答
5. recorder.record_interaction(... prompt_version_id=version_id)  ← 埋点落库
```

**关键点**：
- **分流种子**：优先用 `conversation_id`（天然会话粘性——同一会话同一版本）；无会话则用 interaction 生成的稳定种子。
- **稳定哈希**：`int(hashlib.sha256(f"{seed}:{prompt_key}".encode()).hexdigest(), 16) % 100`，可复现、可复算，排查时能还原分流。
- **fail-safe**：experiment/registry 任何异常 → 回退到 file 默认模板 + `prompt_version_id=None`，问答绝不因治理逻辑失败（与现有 recorder「side channel 失败即吞」风格一致）。

## 6. 读取链路（聚合 + 显著性 API）

### 6.1 报告 API

`GET /experiments/{kb_id}/{prompt_key}/report` — 实验对比报告（只读，权限沿用质量评估读权限 / `QA_FEEDBACK`）。

处理流程：
```
1. 查该 kb+key 的实验配置，取 variants 的 version_id 列表
2. 按 prompt_version_id 分组聚合 QAInteraction + QAEvaluation + QAFeedback：
   每组算 → 样本量 n、平均 faithfulness/relevance/citation_accuracy、好评率
3. 两两版本对比（以 file 默认为基线），逐指标独立跑显著性：
   ├─ 连续型质量分 → Welch's t-test → p值 + 均值差 + 95% CI
   └─ 好评率 → 双比例 z-test → p值 + 比例差 + 95% CI
4. 小样本门槛：任一组 n < 30 → 该指标标 "insufficient_sample"，不下显著结论
```

响应结构（每指标独立、不加权）：
```json
{
  "prompt_key": "rag_qa",
  "variants": [
    {"version_id": "A", "label": "v1-default", "n": 120,
     "metrics": {"faithfulness": {"mean": 0.82}, "positive_rate": {"rate": 0.75}}},
    {"version_id": "B", "label": "v2-concise", "n": 118, "metrics": {}}
  ],
  "comparisons": [
    {"baseline": "A", "variant": "B", "metric": "faithfulness",
     "test": "welch_t", "p_value": 0.03, "diff": 0.05,
     "ci95": [0.01, 0.09], "verdict": "B significantly better"},
    {"baseline": "A", "variant": "B", "metric": "positive_rate",
     "test": "two_proportion_z", "p_value": 0.21, "diff": 0.03,
     "ci95": [-0.02, 0.08], "verdict": "no significant difference"}
  ]
}
```

### 6.2 运营写操作 API（需管理权限）

- `POST /prompt-versions` — 新建 DB 版本（source=db）
- `POST /experiments` / `PATCH /experiments/{id}` — 建/改/停实验、调配比

## 7. 统计实现细节（`stats.py`，纯标准库）

- **Welch's t-test**：`statistics.mean/variance` 算两组均值方差 → t 统计量 + Welch–Satterthwaite 自由度 → p 值用 t 分布近似（标准库无 t 分布 CDF：小自由度用数值积分/近似式，大自由度退化为正态 `math.erf`）。95% CI = 均值差 ± t临界值 × 标准误。
- **双比例 z-test**：合并比例算 z 统计量 → 正态 CDF（`math.erf`）出 p 值 + Wald 区间。
- 全部为纯函数：输入样本列表，输出 dataclass，无 DB/IO。
- 边界：方差为 0、n<2、除零 → 返回 `insufficient_sample`，不抛异常。

## 8. 错误处理

- 运行时分流/渲染 fail-safe，回退 file 默认，`prompt_version_id=None`。
- registry 缓存失效：DB 版本增改后主动 invalidate 对应 key 的缓存条目。
- 报告 API 若某组无数据 → 该组 n=0，指标返回 null，不报错。

## 9. 测试计划

- `stats`：已知输入对拍（手算/在线计算器核对的固定用例）验证 p 值、CI；边界（0 方差、小样本）。
- `registry`：file→DB 覆盖优先级、缓存命中与失效、DB 空时回退 file。
- `experiment`：稳定哈希分流可复现、配比区间正确、无实验/已停回退默认、异常 fail-safe。
- 端到端：建版本 → 建实验 → 模拟多次问答（验证 `prompt_version_id` 落库且分布符合配比）→ 造评分/反馈 → 调 report API 验证聚合与显著性结论。

## 10. 迁移

- Alembic 迁移：新增 `prompt_versions`、`prompt_experiments` 两表 + `QAInteraction.prompt_version_id` 列。
- 首次同步脚本：把 file 模板写入 `prompt_versions`（source=file）。
- 迁移沿用项目惯例「待手动跑」。

## 11. 不在本期范围（后续 ticket）

- 扩展治理到 agent 各模式（direct/react/plan_execute/langgraph）。
- 自动晋级（显著胜出后自动设为默认并结束实验）。
- 多重比较校正（多指标/多版本同时检验时的 p 值校正）。
- 运营后台 UI（本期仅提供 API）。
