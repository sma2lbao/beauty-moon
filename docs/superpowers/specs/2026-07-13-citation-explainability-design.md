# 引用与可解释性增强 — 设计文档

- 日期：2026-07-13
- 状态：已定稿（待评审）
- 范围：本文档包含 **总体架构纲要（A/B/C 三层）** 与 **第一层「Source 富化」的详细设计**。第二、三层为后续独立子项目，本文档仅锁定其接口衔接方向。

---

## 1. 背景与动机

RAG 系统答案的可信度取决于引用是否准确、可追溯。当前实现的缺口：

- `SourceResponse` 只有 `document_id`、`document_title`、`chunk_content`（截断 200 字）、`relevance_score`，缺少原文定位信息。
- Chunk 仅记录 `chunk_index`，**没有** 字符偏移、标题层级、页码等定位数据。
- 答案生成 prompt 虽标注 `[Source 1]`/`[Source 2]`，但不要求 LLM 逐句引用，答案与来源之间**没有可机读的对应关系**。
- 没有任何 faithfulness / grounding 校验，无法判断答案是否真被来源支撑。

企业用户需要"定位原文、看清出处、确认可信"才能建立信任。这三项诉求天然对应三层能力。

---

## 2. 总体架构纲要（三层衔接蓝图）

### 2.1 分层与依赖

```
A. Source 富化（本文档详细展开）
   产出：每个 chunk 带 char offset + heading path + chunk_index
   API：SourceResponse 新增 4 个可选字段
        │
        ▼ 提供“稳定、细粒度的来源定位”
B. 内联引用（后续独立子项目）
   产出：答案文本内嵌 [1][2] 标记，标记 ↔ source 序号可机读映射
   依赖：A 的 chunk 序号/定位，让 “[1]” 能精确指向原文位置
        │
        ▼ 提供“每句话声称来自哪个来源”
C. 忠实性校验（后续独立子项目）
   产出：逐句 grounding 校验 + 无支撑句标注 + citation accuracy 指标
   依赖：B 的句↔源映射，才能验证“这句话是否真被来源支撑”
```

实现顺序为 **A → B → C**，每层为下一层铺路，且每层单独上线都能交付可感知价值。

### 2.2 数据结构演进原则（贯穿三层）

- A 层引入的 chunk 定位信息是**地基**，B/C **只增不改**：B 复用 A 的 offset/heading 生成引用锚，C 复用 B 的映射做校验。
- API 兼容策略统一为**新增可选字段**，任何一层都不破坏既有 `SourceResponse` 契约。
- 存量数据统一策略：**新逻辑仅对新摄取/重处理生效**，旧数据字段留空、优雅降级；回填能力列为各层的"后续可选增强"。

### 2.3 本次范围边界（明确不做）

- ❌ 页码提取（需改造文件解析管线）→ A 层后续可选增强
- ❌ 可点击深链 `source_url#anchor` → A 层后续可选增强
- ❌ 存量 chunk 回填脚本 → 后续可选增强
- ❌ B 层内联引用、C 层忠实性校验 → 各自独立子项目，本文档只锁接口方向

---

## 3. 第一层「Source 富化」详细设计

### 3.1 目标

让每个检索到的来源携带**确定性可算的原文定位信息**，使用户能从引用回到原文的准确区间与结构位置：

- `char_start` / `char_end`：chunk 在 `Document.content` 中的字符起止偏移。
- `heading_path`：chunk 所属的标题层级路径（如 `"第2章 环境准备 > 2.1 安装依赖"`）。
- `chunk_index`：已有，一并透出。

### 3.2 组件与职责边界

新增一个**独立、可单测的定位提取单元**，插入现有切分流程，不侵入检索/生成：

```
新增单元：app/services/chunk_locator.py
  职责：给定 document.content + 切分结果，计算每个 chunk 的
        char_start / char_end 和 heading_path
  输入：原文全文 content、各 split 的 page_content
  输出：list[LocatorInfo]（与 chunk 一一对应）
  依赖：无外部依赖，纯字符串计算（可独立测试）
```

- **它做什么**：只负责"算定位"，不碰 DB、不碰向量库。
- **怎么用**：`DocumentProcessor.split_document` 调它，把结果并入 chunk dict。
- **依赖什么**：仅标准库 + 已有的 markdown/文本结构判断逻辑。

`LocatorInfo` 建议为轻量结构（dataclass 或 TypedDict）：`{char_start: int | None, char_end: int | None, heading_path: str | None}`。

### 3.3 数据流

```
process_document
  └─ split_document(document, doc_metadata)
       ├─ text_splitter.split_documents([content])   # 现有
       ├─ chunk_locator.locate(content, splits)       # 新增
       │    ├─ 顺序扫描 content，用 str.find(游标推进) 定位每个 split → char_start/end
       │    └─ 预解析 content 的 heading 结构 → 按 offset 归属 heading_path
       └─ 合入 chunk dict: {..., char_start, char_end, heading_path}
  └─ Chunk(**chunk_dict) 落库（新增列）
```

- **offset 计算**：维护一个游标 `cursor`，对每个 split 执行 `content.find(split_text, cursor)`，命中后将 `cursor` 推进到 `char_end`，避免重复内容误匹配；找不到时该 chunk offset 降级为 `null`（不阻断摄取）。
- **heading 解析**：扫描 markdown 风格标题（`#`/`##`…）建立 `(offset, level, title)` 列表并构建层级栈；每个 chunk 按其 `char_start` 落在哪个标题区间，回溯栈得到从顶层到最近层级的路径，用 ` > ` 连接。纯文本无标题 → `heading_path = null`。

### 3.4 数据模型与 API 变更

**Chunk 模型（新增 3 列，全部 nullable）**

```python
# app/db/models.py — class Chunk
char_start:   Mapped[int | None] = mapped_column(Integer, nullable=True)
char_end:     Mapped[int | None] = mapped_column(Integer, nullable=True)
heading_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
# chunk_index 已存在，无需改
```

- Alembic 迁移：`add_column`，均 nullable，存量行自动为 `null`，零回填、零锁风险。
- `heading_path` 用 `String(1000)`，超长按 3.5 的规则从末尾截断。

**检索层透传**

- `rag_graph.retrieve_node` 组装 `retrieved_docs` 时，从 chunk 读出并带上 4 个字段（`chunk_index` / `char_start` / `char_end` / `heading_path`）。
- 复用 KB 归属校验那步已执行的 SQL 查询（`validate_retrieved_docs_for_knowledge_base`），顺带 `select` 出定位列，避免额外查询。
- 向量库 payload **无需改动**——定位字段从 SQL `Chunk` 行取即可。
- `format_sources` 一并输出这些字段。

**API 响应（新增可选字段，向后兼容）**

```python
# SourceResponse
chunk_index:  int | None = None
char_start:   int | None = None
char_end:     int | None = None
heading_path: str | None = None
```

`AnswerResponse` / `MultiTurnAnswerResponse` 中的 sources 自动继承。老客户端无感，质量评估模块（消费 sources）不受影响。

### 3.5 错误处理（全程 fail-safe，绝不阻断摄取）

- offset 未命中（重复/被 splitter 规整过的文本）→ 该 chunk offset 置 `null`，继续处理后续 chunk。
- heading 解析异常 → 整篇 `heading_path` 置 `null`，记 warning 日志，摄取照常完成。
- `heading_path` 超 1000 字符 → 从**末尾**截断（保留最靠近 chunk 的层级最有用），前缀加 `…`。

### 3.6 测试范围

**单元测试 `chunk_locator`：**

- 正常 markdown（多级标题）→ offset 连续、`heading_path` 正确。
- 纯文本无标题 → `heading_path` 全 `null`，offset 正常。
- 重复内容段落 → 游标推进保证 offset 不回退误匹配。
- 超长 heading → 末尾截断，前缀 `…`。
- split 在原文找不到 → 该 chunk offset 为 `null`，不抛异常。

**集成测试：**

- 摄取一篇结构化文档 → 查 chunk 行验证新列填充正确 → 走一次 QA → 断言 `SourceResponse` 带出定位字段。

**回归测试：**

- 存量（无新列 / 字段为 `null`）路径下 API 仍正常返回，定位字段为 `null`，前端老逻辑（用摘要）不受影响。

---

## 4. 后续子项目（本文档不展开）

| 子项目 | 依赖 | 核心产出 |
| --- | --- | --- |
| B. 内联引用 | A | 答案内嵌 `[n]` 标记 + 标记↔source 可机读映射 |
| C. 忠实性校验 | B | 逐句 grounding 校验、无支撑句标注、citation accuracy 指标 |
| A 后续可选 | A | 页码提取、可点击深链、存量 chunk 回填脚本 |

每个子项目将各自走 spec → plan → 实现循环。
