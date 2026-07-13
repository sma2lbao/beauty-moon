# 引用与可解释性增强（第一层 Source 富化）—— 合入后跟进项

来源：`feat/citation-source-enrichment`（merged to main 2026-07-13）最终整体代码审查。
主 spec：[docs/superpowers/specs/2026-07-13-citation-explainability-design.md](../superpowers/specs/2026-07-13-citation-explainability-design.md)
实现计划：[docs/superpowers/plans/2026-07-13-source-enrichment.md](../superpowers/plans/2026-07-13-source-enrichment.md)

最终整体审查结论：**可合入**，0 Critical / 0 Important。以下项均为**预存问题（非本分支引入）或有意延后**，非阻断缺陷。

---

## 1. `document_title` 始终为 None（Minor，功能缺口）

- **现状**：`/qa/query` 与 `/qa/multi-turn` 两端点的 `SourceResponse` 构造循环注释写着「Enrich sources with document titles」，但从未传入 `document_title`，该字段恒为 `None`。这是**本分支之前就存在的行为**，本次按计划「保持现有写法不变」未动它。
- **张力**：`SourceResponse.document_title` 字段早已定义，前端「定位原文」体验依赖标题展示，但一直没填充。
- **建议**：在 enrich 循环里按 `source["document_id"]` 批量查 `Document.title` 回填（一次性 `IN` 查询，避免 N+1），与本次新增的 offset/heading_path 一起构成完整的引用定位信息。
- **备注**：这属于「引用富化」本意的一部分，且成本很低，建议优先跟进。

## 2. 预存 ruff 警告（Minor，非本分支引入）

以下警告在 `main` 分支已存在，本次改动未触碰对应代码行，故未修（守范围纪律）。可批量清理：

- `app/graph/rag_graph.py`：4 个警告（UP035 过时 typing 导入、F841 未用变量、E501 x2 行超长）。
- `app/api/routes.py`：3 个警告（B904 `raise ... from`、E501 x2 @ 814/816/880 行）。
- `tests/graph/test_knowledge_base_filter.py`：F401 未用导入 `from app.db.database import get_db`（该测试用 `patch("app.graph.rag_graph.get_db", ...)` 注入，导入本身冗余）。
- **建议**：单开一个「ruff 存量清理」批处理 ticket，与本功能解耦。

## 3. 测试覆盖完整性（Minor，非问题但可增强）

- 部分测试仅断言首个 chunk 的定位字段（如 `test_split_document_attaches_locator_fields` 只查 `chunks[0]`）；`char_end` 未在每个测试独立断言。
- **现状判断**：跨测试已有覆盖——`test_markdown_multi_level_headings` 断言了两个 chunk 的 offset，fail-safe 测试断言 `char_end is not None`，`test_format_sources_includes_locator_fields` 覆盖 `char_end` 透出。功能无盲区。
- **建议**：若后续 heading/offset 逻辑演进，可补一个「多 chunk 逐项定位」的参数化测试增强防回归。

## 4. 过程改进：任务级回归范围（非代码项）

- **观察**：Task 4 改写 `format_sources` / `validate_retrieved_docs_for_knowledge_base` 的输出契约，影响了 `test_rag_graph.py`（4 处）与 `test_knowledge_base_filter.py`（1 处）共 5 个存量测试，但这些回归在 Task 4 阶段未被发现（该任务只跑了 brief 指定的相关测试），最终由 Task 6 的全量回归兜住并修复。
- **结论**：全量 566 passed 证明无遗漏回归面，但**改动公共输出契约的任务，任务级验证就应跑全量回归**，而非仅 brief 列出的相关测试。后续 plan 编写时，对「修改 format_sources / 校验函数等被广泛消费的接口」的任务，应在 brief 的回归步骤里显式要求全量。

---

## 后续层级（来自主 spec 纲要，非本次范围）

本次仅交付三层体系的**第一层（A. Source 富化）**。以下为纲要中已锁定方向、待各自独立 spec 展开：

- **B. 内联引用**：答案文本内嵌 `[n]` 标记 + 标记↔source 可机读映射（依赖本层的 offset/heading）。
- **C. 忠实性校验**：逐句 grounding 校验、无支撑句标注、citation accuracy 指标（依赖 B 的句↔源映射）。
- **A 层后续可选增强**：页码提取、可点击深链 `source_url#anchor`、存量 chunk 定位回填脚本。
