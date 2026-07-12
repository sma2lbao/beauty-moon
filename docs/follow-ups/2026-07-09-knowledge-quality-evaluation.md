# 知识质量评测 —— 合入后跟进项

来源：`feat/p1-quality-evaluation`（merged to main 2026-07-09）最终整体代码审查。
主 spec：[docs/superpowers/specs/2026-07-09-knowledge-quality-evaluation-design.md](../superpowers/specs/2026-07-09-knowledge-quality-evaluation-design.md)

以下项在功能合入时**已知并有意延后**，非阻断缺陷。按优先级排列。

---

## 1. `QAInteraction.sources` 存储成本与 PII（Important）

- **现状**：每条交互持久化整个 `sources` 列表，含 `chunk_content` 全文（`app/quality/recorder.py` + `app/db/models.py`）。
- **张力**：spec 第 87 行明确要求存「回答那一刻的检索快照」（非外键引用），因为文档后续会被改/删，faithfulness / citation 打分必须回溯当时上下文——**这是有意设计，不能简单改成只存 chunk_id 现取**。
- **待权衡**：在「保留可回溯快照」与「存储膨胀 / 用户提问+回答+原文全部入库的 PII 外溢」之间取平衡。候选方案：
  - 对 `chunk_content` 加长度截断（保留前 N 字符，够 judge 判分即可）。
  - 引入 TTL / 归档策略（评分完成 + 保留窗口后清理原文，仅留分数与元数据）。
  - 敏感字段脱敏。
- **验收**：不破坏 faithfulness / citation 回溯能力的前提下，降低单条存储体积并给出数据保留策略。

## 2. `parse_judge_response` 解析加固（Important）

- **现状**：`app/quality/judge.py` 用贪婪正则 `re.search(r"\{.*\}", raw, re.DOTALL)` 提取 JSON。
- **风险**：贪婪 `.*` 跨行会把首个 `{` 到**最末** `}` 全吞下，LLM 输出里若含 markdown/示例 JSON 会误匹配，拉低评分完成率（已被 `_run_eval_task` 兜底成 FAILED，不影响主流程）。
- **建议**：先尝试 `json.loads(raw)` 直解 → 失败再用非贪婪 `re.search(r"\{.*?\}", ...)` → 对 3 项分数 clamp 到 [0,1]。
- **备注**：贪婪正则是原 plan（Task 5）指定方案，当时裁定「plan 指定且降级安全」暂不改；此处为质量提升项。

## 3. Minor 清理（可批量处理）

- `app/quality/aggregation.py`：`datetime.utcnow()` 已弃用 → `datetime.now(timezone.utc)`（注意与 `created_at` 的 tz-naive 比较需保持一致）。
- `app/quality/aggregation.py`：total / mode / feedback / error / avg 五次针对同一 KB+时间窗的分开查询可合并为单次 GROUP BY（效率）。
- `app/quality/aggregation.py`：`by_retrieval_mode` 推导用 `if mode` 会连带过滤空串，建议 `if mode is not None`。
- `app/quality/judge.py`：`judge_model` 存的是 provider 标识（如 `openai`）而非具体模型 id，审计溯源意义有限，建议对齐真实模型名。
- `app/quality/judge.py`：`get_judge()` 全局 singleton 无锁，多线程首访问理论有极小竞态。
- migration `20260709_0009`：手写 index 名 `ix_qa_interactions_kb` 与 models 侧 `index=True` 的默认名不一致，日后 `alembic --autogenerate` 会反复报 index 差异 → 建议模型侧改用显式 `Index("ix_qa_interactions_kb", ...)` 对齐。
