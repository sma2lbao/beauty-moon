# Source 富化（引用与可解释性增强 · 第一层）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个检索到的来源携带确定性可算的原文定位信息（字符偏移 `char_start`/`char_end`、标题层级 `heading_path`、已有的 `chunk_index`），并通过 `SourceResponse` 向后兼容地透出。

**Architecture:** 新增一个无副作用的纯字符串计算单元 `chunk_locator`，在 `DocumentProcessor.split_document` 里被调用，把定位信息并入 chunk dict 并落库到 `Chunk` 新增的 3 个 nullable 列。检索节点 `retrieve_node` 从已执行的 KB 归属校验 SQL 里顺带取出定位列，经 `format_sources` 输出到 API。全程 fail-safe，任何定位计算失败都降级为 `null`，绝不阻断摄取。

**Tech Stack:** Python 3.14、FastAPI、SQLAlchemy（MySQL / CHAR(36) 主键）、Alembic、LangGraph、Pydantic v2、pytest。

## Global Constraints

- 包管理器统一用 `npm`；测试通过 `npm exec nx test luna-corpus` 或直接 `pytest` 运行（仓库根 `pyproject.toml` 已配置 pytest）。
- 所有新增 DB 列必须 `nullable=True`，存量行自动为 `null`，零回填、零锁风险。
- API 兼容策略：只在 `SourceResponse` **新增可选字段**（默认 `None`），不改既有字段、不破坏契约。
- 定位计算全程 **fail-safe**：offset 未命中 → 该 chunk 置 `null`；heading 解析异常 → 整篇 `heading_path` 置 `null` 并记 warning；摄取流程不得因定位失败中断。
- `heading_path` 存储上限 `String(1000)`，超长从**末尾**截断（保留最靠近 chunk 的层级），前缀加 `…`。
- Alembic 迁移 `down_revision` 必须指向当前最新版本 `20260712_0010`；新 revision id 采用日期序号格式 `20260713_0011`。
- 定位单元 `chunk_locator` 不得依赖 DB / 向量库 / 网络，仅标准库 + 纯字符串计算，保证可独立单测。

---

### Task 1: chunk_locator 定位计算单元

**Files:**
- Create: `apps/luna-corpus/app/services/chunk_locator.py`
- Test: `apps/luna-corpus/tests/test_chunk_locator.py`

**Interfaces:**
- Consumes: 无（纯字符串计算，仅标准库）。
- Produces:
  - `LocatorInfo` — `TypedDict`，键：`char_start: int | None`、`char_end: int | None`、`heading_path: str | None`。
  - `locate(content: str, splits: list[str]) -> list[LocatorInfo]` — 输入原文全文与各 split 的文本（顺序与切分一致），返回与 splits 一一对应、等长的定位信息列表。全程 fail-safe，绝不抛异常。
  - 常量 `MAX_HEADING_PATH = 1000`；heading 路径分隔符 ` > `。

- [ ] **Step 1: 写失败测试（正常 markdown 多级标题）**

创建 `apps/luna-corpus/tests/test_chunk_locator.py`：

```python
"""chunk_locator 定位计算单元测试。"""
from app.services.chunk_locator import LocatorInfo, locate


def test_markdown_multi_level_headings():
    content = (
        "# 第2章 环境准备\n"
        "\n"
        "## 2.1 安装依赖\n"
        "先安装依赖包。\n"
        "## 2.2 配置\n"
        "然后配置环境。\n"
    )
    splits = ["先安装依赖包。", "然后配置环境。"]

    result = locate(content, splits)

    assert len(result) == 2
    # 第一段落在 2.1 下
    assert result[0]["char_start"] == content.index("先安装依赖包。")
    assert result[0]["char_end"] == result[0]["char_start"] + len("先安装依赖包。")
    assert result[0]["heading_path"] == "第2章 环境准备 > 2.1 安装依赖"
    # 第二段落在 2.2 下
    assert result[1]["heading_path"] == "第2章 环境准备 > 2.2 配置"
    assert result[1]["char_start"] == content.index("然后配置环境。")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/test_chunk_locator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.chunk_locator'`

- [ ] **Step 3: 写最小实现**

创建 `apps/luna-corpus/app/services/chunk_locator.py`：

```python
"""Chunk 定位计算单元：为每个 chunk 计算字符偏移与标题层级路径。

纯字符串计算，无 DB / 向量库 / 网络依赖，可独立单测。全程 fail-safe：
任何计算失败都降级为 None，绝不抛异常、绝不阻断摄取。
"""
import logging
import re

from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

MAX_HEADING_PATH = 1000
_HEADING_SEP = " > "
# markdown ATX 标题：行首 1-6 个 # + 空格 + 标题文本
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$", re.MULTILINE)


class LocatorInfo(TypedDict):
    """单个 chunk 的定位信息。"""

    char_start: int | None
    char_end: int | None
    heading_path: str | None


def _parse_headings(content: str) -> list[tuple[int, int, str]]:
    """解析 markdown 标题，返回 (offset, level, title) 列表（按 offset 升序）。"""
    headings: list[tuple[int, int, str]] = []
    for m in _HEADING_RE.finditer(content):
        level = len(m.group(1))
        title = m.group(2).strip()
        if title:
            headings.append((m.start(), level, title))
    return headings


def _heading_path_at(headings: list[tuple[int, int, str]], offset: int) -> str | None:
    """给定字符偏移，回溯层级栈得到从顶层到最近层级的标题路径。"""
    stack: list[tuple[int, str]] = []  # (level, title)
    for h_offset, level, title in headings:
        if h_offset > offset:
            break
        # 弹出所有 >= 当前 level 的栈顶，保证层级递增
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
    if not stack:
        return None
    path = _HEADING_SEP.join(title for _, title in stack)
    if len(path) > MAX_HEADING_PATH:
        # 从末尾保留最靠近 chunk 的层级
        path = "…" + path[-(MAX_HEADING_PATH - 1):]
    return path


def locate(content: str, splits: list[str]) -> list[LocatorInfo]:
    """为每个 split 计算 char_start/char_end 与 heading_path。

    Args:
        content: 文档原文全文。
        splits: 各 chunk 的文本，顺序与切分结果一致。

    Returns:
        与 splits 等长的定位信息列表，一一对应。
    """
    try:
        headings = _parse_headings(content)
    except Exception:  # noqa: BLE001 — fail-safe，heading 解析失败整篇降级
        logger.warning("heading 解析失败，heading_path 全部降级为 None", exc_info=True)
        headings = []
        heading_disabled = True
    else:
        heading_disabled = False

    result: list[LocatorInfo] = []
    cursor = 0
    for split_text in splits:
        char_start: int | None = None
        char_end: int | None = None
        idx = content.find(split_text, cursor)
        if idx != -1:
            char_start = idx
            char_end = idx + len(split_text)
            cursor = char_end  # 游标推进，避免重复内容误匹配

        heading_path = (
            None
            if heading_disabled or char_start is None
            else _heading_path_at(headings, char_start)
        )
        result.append(
            LocatorInfo(
                char_start=char_start,
                char_end=char_end,
                heading_path=heading_path,
            )
        )
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_chunk_locator.py -v`
Expected: PASS

- [ ] **Step 5: 补充边界测试**

在 `tests/test_chunk_locator.py` 追加：

```python
def test_plain_text_no_headings():
    content = "第一段没有标题。\n\n第二段也没有。"
    splits = ["第一段没有标题。", "第二段也没有。"]

    result = locate(content, splits)

    assert [r["heading_path"] for r in result] == [None, None]
    assert result[0]["char_start"] == 0
    assert result[1]["char_start"] == content.index("第二段也没有。")


def test_repeated_content_cursor_advances():
    # 相同文本出现两次，游标推进保证第二个 chunk 不回退误匹配
    content = "重复段。\n重复段。"
    splits = ["重复段。", "重复段。"]

    result = locate(content, splits)

    assert result[0]["char_start"] == 0
    assert result[1]["char_start"] == content.index("重复段。", 1)
    assert result[1]["char_start"] > result[0]["char_start"]


def test_split_not_found_yields_none():
    content = "原文内容。"
    splits = ["不存在的文本"]

    result = locate(content, splits)

    assert result[0]["char_start"] is None
    assert result[0]["char_end"] is None
    assert result[0]["heading_path"] is None


def test_oversized_heading_truncated_from_end():
    long_title = "标" * 1100
    content = f"# {long_title}\n正文。"
    splits = ["正文。"]

    result = locate(content, splits)

    path = result[0]["heading_path"]
    assert path is not None
    assert len(path) <= 1000
    assert path.startswith("…")
    # 末尾层级被保留
    assert path.endswith("标")
```

- [ ] **Step 6: 运行全部 chunk_locator 测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_chunk_locator.py -v`
Expected: PASS（5 个测试全绿）

- [ ] **Step 7: 提交**

```bash
git add apps/luna-corpus/app/services/chunk_locator.py apps/luna-corpus/tests/test_chunk_locator.py
git commit -m "feat(citation): add chunk_locator for char offset and heading path"
```

---

### Task 2: Chunk 模型新增定位列 + Alembic 迁移

**Files:**
- Modify: `apps/luna-corpus/app/db/models.py`（`class Chunk`，约 369-388 行）
- Create: `apps/luna-corpus/alembic/versions/20260713_0011_chunk_locator_columns.py`
- Test: `apps/luna-corpus/tests/test_chunk_locator_migration.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `Chunk.char_start: int | None`、`Chunk.char_end: int | None`、`Chunk.heading_path: str | None` 三个 ORM 属性（均 nullable）。
  - Alembic revision `20260713_0011`，`down_revision = "20260712_0010"`。

- [ ] **Step 1: 写失败测试（ORM 列存在且可写 null 与非 null）**

创建 `apps/luna-corpus/tests/test_chunk_locator_migration.py`：

```python
"""Chunk 定位列的 ORM 层测试（内存 SQLite）。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Chunk, ContentType


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_chunk_locator_columns_persist():
    db = _session()
    chunk = Chunk(
        document_id="doc1",
        content="正文",
        content_type=ContentType.TEXT,
        chunk_index=0,
        char_start=10,
        char_end=12,
        heading_path="第2章 > 2.1 安装",
    )
    db.add(chunk)
    db.commit()

    row = db.query(Chunk).first()
    assert row.char_start == 10
    assert row.char_end == 12
    assert row.heading_path == "第2章 > 2.1 安装"


def test_chunk_locator_columns_nullable():
    db = _session()
    chunk = Chunk(
        document_id="doc1",
        content="正文",
        content_type=ContentType.TEXT,
        chunk_index=0,
    )
    db.add(chunk)
    db.commit()

    row = db.query(Chunk).first()
    assert row.char_start is None
    assert row.char_end is None
    assert row.heading_path is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/test_chunk_locator_migration.py -v`
Expected: FAIL — `TypeError: 'char_start' is an invalid keyword argument for Chunk`

- [ ] **Step 3: 在 Chunk 模型新增三列**

修改 `apps/luna-corpus/app/db/models.py`，在 `class Chunk` 的 `chunk_index` 行之后加入：

```python
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
```

（`Integer`、`String` 已在文件顶部导入，无需改导入。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_chunk_locator_migration.py -v`
Expected: PASS

- [ ] **Step 5: 编写 Alembic 迁移**

创建 `apps/luna-corpus/alembic/versions/20260713_0011_chunk_locator_columns.py`：

```python
"""citation source enrichment: chunk locator columns

Revision ID: 20260713_0011
Revises: 20260712_0010
Create Date: 2026-07-13

"""
import sqlalchemy as sa
from alembic import op

revision = "20260713_0011"
down_revision = "20260712_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("char_start", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("char_end", sa.Integer(), nullable=True))
    op.add_column(
        "chunks", sa.Column("heading_path", sa.String(length=1000), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chunks", "heading_path")
    op.drop_column("chunks", "char_end")
    op.drop_column("chunks", "char_start")
```

- [ ] **Step 6: 校验迁移链完整（离线检查，不需真实 DB）**

Run: `cd apps/luna-corpus && python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; s=ScriptDirectory.from_config(Config('alembic.ini')); h=s.get_current_head(); print('head=', h); assert h=='20260713_0011', h; print('down=', s.get_revision(h).down_revision)"`
Expected: 输出 `head= 20260713_0011` 与 `down= 20260712_0010`，无 `Multiple head revisions` 报错。

- [ ] **Step 7: 提交**

```bash
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/alembic/versions/20260713_0011_chunk_locator_columns.py apps/luna-corpus/tests/test_chunk_locator_migration.py
git commit -m "feat(citation): add chunk locator columns and migration"
```

---

### Task 3: 摄取流程写入定位信息

**Files:**
- Modify: `apps/luna-corpus/app/services/document_processor.py`（`split_document`，约 58-87 行）
- Test: `apps/luna-corpus/tests/test_document_processor_locator.py`

**Interfaces:**
- Consumes: `chunk_locator.locate(content, splits)`（Task 1）；`Chunk.char_start/char_end/heading_path`（Task 2）。
- Produces: `split_document` 返回的每个 chunk dict 新增键 `char_start`、`char_end`、`heading_path`；这些键随 `Chunk(**chunk_dict)` 落库。

- [ ] **Step 1: 写失败测试（split_document 输出带定位字段）**

创建 `apps/luna-corpus/tests/test_document_processor_locator.py`：

```python
"""摄取切分把定位信息并入 chunk dict 的测试。"""
from unittest.mock import MagicMock

from app.services.document_processor import DocumentProcessor


def test_split_document_attaches_locator_fields():
    proc = DocumentProcessor(chunk_size=1000, chunk_overlap=0)
    document = MagicMock()
    document.id = "doc1"
    document.content = "# 标题A\n第一段内容。\n## 标题B\n第二段内容。"

    chunks = proc.split_document(document, doc_metadata=None)

    assert len(chunks) >= 1
    first = chunks[0]
    # 定位字段存在
    assert "char_start" in first
    assert "char_end" in first
    assert "heading_path" in first
    # char_start 指向该 chunk 内容在原文中的位置
    assert first["char_start"] == document.content.find(first["content"])
    assert first["char_end"] == first["char_start"] + len(first["content"])
    # 内容落在某个标题下
    assert first["heading_path"] is not None
    assert "标题A" in first["heading_path"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/test_document_processor_locator.py -v`
Expected: FAIL — `KeyError: 'char_start'`（chunk dict 尚无该键）

- [ ] **Step 3: 在 split_document 里调用 locate 并合入 chunk dict**

修改 `apps/luna-corpus/app/services/document_processor.py`。文件顶部导入区加入：

```python
from app.services.chunk_locator import locate as locate_chunks
```

将 `split_document` 方法体替换为：

```python
    def split_document(
        self, document: Document, doc_metadata: dict | None = None
    ) -> list[dict[str, Any]]:
        """Split document into chunks.

        Args:
            document: Document to split
            doc_metadata: Normalized document metadata to attach to each chunk

        Returns:
            List of chunk dictionaries
        """
        langchain_doc = LCDocument(
            page_content=document.content,
            metadata={"document_id": document.id},
        )

        splits = self.text_splitter.split_documents([langchain_doc])

        # 计算每个 split 在原文中的字符偏移与标题层级（fail-safe）
        locators = locate_chunks(
            document.content, [s.page_content for s in splits]
        )

        chunks = []
        for i, split in enumerate(splits):
            loc = locators[i]
            chunks.append({
                "document_id": document.id,
                "content": split.page_content,
                "content_type": self.detect_content_type(split.page_content),
                "chunk_metadata": doc_metadata or None,
                "chunk_index": i,
                "char_start": loc["char_start"],
                "char_end": loc["char_end"],
                "heading_path": loc["heading_path"],
            })

        return chunks
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_document_processor_locator.py -v`
Expected: PASS

- [ ] **Step 5: 回归 — 确认既有文档处理测试仍通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_document_processor_metadata.py tests/test_ingestion_metadata.py -v`
Expected: PASS（既有测试不受影响）

- [ ] **Step 6: 提交**

```bash
git add apps/luna-corpus/app/services/document_processor.py apps/luna-corpus/tests/test_document_processor_locator.py
git commit -m "feat(citation): attach locator info to chunks during ingestion"
```

---

### Task 4: 检索层透传定位字段

**Files:**
- Modify: `apps/luna-corpus/app/graph/rag_graph.py`（`validate_retrieved_docs_for_knowledge_base` 约 29-58 行、`format_sources` 约 61-72 行、`retrieve_node` 约 148-163 行）
- Test: `apps/luna-corpus/tests/test_rag_source_locator.py`

**Interfaces:**
- Consumes: `Chunk.char_start/char_end/heading_path/chunk_index`（Task 2）；`retrieved_docs` 中每项含 `chunk_id`、`document_id`、`content`、`score`。
- Produces:
  - `format_sources` 输出的每个 source dict 新增键 `chunk_index`、`char_start`、`char_end`、`heading_path`（缺失时为 `None`）。
  - `validate_retrieved_docs_for_knowledge_base` 在做 KB 归属过滤的同时，把每个存活 doc 补上 `chunk_index/char_start/char_end/heading_path`（从 `Chunk` 行读取）。

- [ ] **Step 1: 写失败测试（format_sources 透出定位字段）**

创建 `apps/luna-corpus/tests/test_rag_source_locator.py`：

```python
"""检索层把 chunk 定位字段透传到 sources 的测试。"""
from app.graph.rag_graph import format_sources


def test_format_sources_includes_locator_fields():
    retrieved = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "content": "一段被引用的原文内容。",
            "score": 0.9,
            "chunk_index": 3,
            "char_start": 100,
            "char_end": 130,
            "heading_path": "第2章 > 2.1 安装",
        }
    ]

    sources = format_sources(retrieved)

    assert sources[0]["chunk_index"] == 3
    assert sources[0]["char_start"] == 100
    assert sources[0]["char_end"] == 130
    assert sources[0]["heading_path"] == "第2章 > 2.1 安装"


def test_format_sources_defaults_missing_locator_to_none():
    # 存量 chunk 无定位字段时应优雅降级为 None
    retrieved = [
        {
            "chunk_id": "c1",
            "document_id": "d1",
            "content": "旧数据内容。",
            "score": 0.5,
        }
    ]

    sources = format_sources(retrieved)

    assert sources[0]["chunk_index"] is None
    assert sources[0]["char_start"] is None
    assert sources[0]["char_end"] is None
    assert sources[0]["heading_path"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/test_rag_source_locator.py -v`
Expected: FAIL — `KeyError: 'chunk_index'`（`format_sources` 尚未输出定位字段）

- [ ] **Step 3: 扩展 format_sources 输出定位字段**

修改 `apps/luna-corpus/app/graph/rag_graph.py` 的 `format_sources`：

```python
def format_sources(retrieved_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format validated retrieved docs as API sources."""
    return [
        {
            "document_id": doc["document_id"],
            "chunk_content": doc["content"][:200] + "..."
            if len(doc["content"]) > 200
            else doc["content"],
            "relevance_score": doc["score"],
            "chunk_index": doc.get("chunk_index"),
            "char_start": doc.get("char_start"),
            "char_end": doc.get("char_end"),
            "heading_path": doc.get("heading_path"),
        }
        for doc in retrieved_docs
    ]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_rag_source_locator.py -v`
Expected: PASS

- [ ] **Step 5: 在 KB 归属校验时补齐定位字段**

修改 `apps/luna-corpus/app/graph/rag_graph.py` 的 `validate_retrieved_docs_for_knowledge_base`，把只查 `Document.id` 改为连带 `Chunk` 定位列，并回填到存活 doc。用 `chunk_id` 关联：

```python
def validate_retrieved_docs_for_knowledge_base(
    retrieved_docs: list[dict[str, Any]],
    knowledge_base_id: str,
) -> list[dict[str, Any]]:
    """Keep only retrieved docs whose SQL document belongs to the knowledge base.

    同时从 Chunk 行补齐定位字段（chunk_index/char_start/char_end/heading_path），
    供 sources 透出。存量 chunk 缺失定位时保持 None。
    """
    chunk_ids = {
        doc.get("chunk_id") for doc in retrieved_docs if doc.get("chunk_id")
    }
    if not chunk_ids:
        return []

    db = next(get_db())
    try:
        rows = (
            db.query(
                Chunk.id,
                Chunk.chunk_index,
                Chunk.char_start,
                Chunk.char_end,
                Chunk.heading_path,
            )
            .join(Document, Chunk.document_id == Document.id)
            .filter(
                Chunk.id.in_(chunk_ids),
                Document.knowledge_base_id == knowledge_base_id,
            )
            .all()
        )
    finally:
        db.close()

    locator_by_chunk = {
        row[0]: {
            "chunk_index": row[1],
            "char_start": row[2],
            "char_end": row[3],
            "heading_path": row[4],
        }
        for row in rows
    }

    validated = []
    for doc in retrieved_docs:
        loc = locator_by_chunk.get(doc.get("chunk_id"))
        if loc is None:
            continue  # 不属于该 KB，过滤掉
        validated.append({**doc, **loc})
    return validated
```

顶部导入区把 `from app.db.models import Document` 改为：

```python
from app.db.models import Chunk, Document
```

- [ ] **Step 6: 写并运行 KB 校验补齐测试**

在 `tests/test_rag_source_locator.py` 追加（用内存 SQLite 建 Document + Chunk）：

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from app.db.models import Base, Chunk, ContentType, Document
from app.graph.rag_graph import validate_retrieved_docs_for_knowledge_base


def _seed_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    doc = Document(
        id="d1", knowledge_base_id="kb1", title="T", content="正文"
    )
    db.add(doc)
    db.add(
        Chunk(
            id="c1", document_id="d1", content="正文",
            content_type=ContentType.TEXT, chunk_index=2,
            char_start=5, char_end=7, heading_path="第1章",
        )
    )
    db.commit()
    return db


def test_validate_backfills_locator_from_chunk():
    db = _seed_session()
    retrieved = [
        {"chunk_id": "c1", "document_id": "d1", "content": "正文", "score": 0.8}
    ]

    with patch("app.graph.rag_graph.get_db", return_value=iter([db])):
        result = validate_retrieved_docs_for_knowledge_base(retrieved, "kb1")

    assert len(result) == 1
    assert result[0]["chunk_index"] == 2
    assert result[0]["char_start"] == 5
    assert result[0]["heading_path"] == "第1章"


def test_validate_filters_foreign_kb():
    db = _seed_session()
    retrieved = [
        {"chunk_id": "c1", "document_id": "d1", "content": "正文", "score": 0.8}
    ]

    with patch("app.graph.rag_graph.get_db", return_value=iter([db])):
        result = validate_retrieved_docs_for_knowledge_base(retrieved, "other_kb")

    assert result == []
```

Run: `cd apps/luna-corpus && python -m pytest tests/test_rag_source_locator.py -v`
Expected: PASS（4 个测试全绿）

- [ ] **Step 7: 回归 — 检索隔离相关测试仍通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_rag_search_filters.py tests/test_hybrid_filters.py -v`
Expected: PASS（既有检索/隔离行为不变）

- [ ] **Step 8: 提交**

```bash
git add apps/luna-corpus/app/graph/rag_graph.py apps/luna-corpus/tests/test_rag_source_locator.py
git commit -m "feat(citation): pass chunk locator fields through retrieval to sources"
```

---

### Task 5: API 响应模型暴露定位字段

**Files:**
- Modify: `apps/luna-corpus/app/api/routes.py`（`SourceResponse` 约 99-105 行；`/ask` 端点里 enrich sources 的循环，约 463-471 行；如 multi-turn 端点也做 enrich，一并对齐）
- Test: `apps/luna-corpus/tests/test_source_response_locator.py`

**Interfaces:**
- Consumes: `format_sources` 输出的 source dict（含 `chunk_index/char_start/char_end/heading_path`，Task 4）。
- Produces: `SourceResponse` 新增可选字段 `chunk_index/char_start/char_end/heading_path`（默认 `None`），`AnswerResponse`/`MultiTurnAnswerResponse` 的 sources 自动继承。

- [ ] **Step 1: 写失败测试（SourceResponse 接受并保留定位字段）**

创建 `apps/luna-corpus/tests/test_source_response_locator.py`：

```python
"""SourceResponse 定位字段的序列化测试。"""
from app.api.routes import SourceResponse


def test_source_response_accepts_locator_fields():
    src = SourceResponse(
        document_id="d1",
        chunk_content="片段",
        relevance_score=0.9,
        chunk_index=3,
        char_start=100,
        char_end=130,
        heading_path="第2章 > 2.1 安装",
    )
    assert src.chunk_index == 3
    assert src.char_start == 100
    assert src.char_end == 130
    assert src.heading_path == "第2章 > 2.1 安装"


def test_source_response_locator_defaults_none():
    # 老客户端/存量数据：不传定位字段应默认 None，保持向后兼容
    src = SourceResponse(
        document_id="d1",
        chunk_content="片段",
        relevance_score=0.5,
    )
    assert src.chunk_index is None
    assert src.char_start is None
    assert src.char_end is None
    assert src.heading_path is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/test_source_response_locator.py -v`
Expected: FAIL — `TypeError`/`ValidationError`：`SourceResponse` 无 `chunk_index` 等字段

- [ ] **Step 3: 在 SourceResponse 新增可选字段**

修改 `apps/luna-corpus/app/api/routes.py` 的 `SourceResponse`：

```python
class SourceResponse(BaseModel):
    """Source reference model."""

    document_id: str
    document_title: str | None = None
    chunk_content: str
    relevance_score: float
    chunk_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    heading_path: str | None = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_source_response_locator.py -v`
Expected: PASS

- [ ] **Step 5: 在端点 enrich sources 时传递定位字段**

修改 `apps/luna-corpus/app/api/routes.py` 中 `/ask` 端点构造 `SourceResponse` 的循环（约 463-471 行），补上定位字段：

```python
    # Enrich sources with document titles
    enriched_sources = []
    for source in result["sources"]:
        enriched_sources.append(
            SourceResponse(
                document_id=source["document_id"],
                document_title=doc_titles.get(source["document_id"]),
                chunk_content=source["chunk_content"],
                relevance_score=source["relevance_score"],
                chunk_index=source.get("chunk_index"),
                char_start=source.get("char_start"),
                char_end=source.get("char_end"),
                heading_path=source.get("heading_path"),
            )
        )
```

> 注意：`document_title` 的取值表达式（此处示意为 `doc_titles.get(...)`）保持该端点**现有**写法不变，只新增 4 个定位字段。若 multi-turn 端点存在同样的 enrich 循环，按相同方式补齐这 4 个字段。

- [ ] **Step 6: 运行相关 API 测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_source_response_locator.py tests/test_integration.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/test_source_response_locator.py
git commit -m "feat(citation): expose chunk locator fields in SourceResponse"
```

---

### Task 6: 端到端集成测试与全量回归

**Files:**
- Test: `apps/luna-corpus/tests/test_citation_e2e.py`

**Interfaces:**
- Consumes: Task 1-5 的全部产出。
- Produces: 无（仅验证）。

- [ ] **Step 1: 写端到端测试（摄取结构化文档 → chunk 落库带定位 → sources 透出）**

创建 `apps/luna-corpus/tests/test_citation_e2e.py`：

```python
"""引用富化端到端：摄取→切分→定位落库→sources 透出。"""
from unittest.mock import MagicMock, patch

from app.services.document_processor import DocumentProcessor
from app.graph.rag_graph import format_sources


def test_ingestion_populates_locator_and_sources_expose_it():
    proc = DocumentProcessor(chunk_size=1000, chunk_overlap=0)
    document = MagicMock()
    document.id = "doc1"
    document.content = "# 第2章\n## 2.1 安装\n安装步骤内容。"

    # 摄取切分阶段：chunk dict 带定位
    chunk_dicts = proc.split_document(document, doc_metadata=None)
    first = chunk_dicts[0]
    assert first["char_start"] is not None
    assert first["heading_path"] is not None
    assert "2.1 安装" in first["heading_path"]

    # 模拟检索结果（把 chunk_index/offset/heading 带上）走 format_sources
    retrieved = [
        {
            "chunk_id": "c1",
            "document_id": "doc1",
            "content": first["content"],
            "score": 0.9,
            "chunk_index": first["chunk_index"],
            "char_start": first["char_start"],
            "char_end": first["char_end"],
            "heading_path": first["heading_path"],
        }
    ]
    sources = format_sources(retrieved)
    assert sources[0]["char_start"] == first["char_start"]
    assert sources[0]["heading_path"] == first["heading_path"]
    assert sources[0]["chunk_index"] == first["chunk_index"]
```

- [ ] **Step 2: 运行端到端测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/test_citation_e2e.py -v`
Expected: PASS

- [ ] **Step 3: 全量测试回归**

Run: `cd apps/luna-corpus && python -m pytest -q`
Expected: 全部 PASS（无回归；新增测试全绿）

- [ ] **Step 4: lint 检查**

Run: `cd apps/luna-corpus && python -m ruff check app/services/chunk_locator.py app/services/document_processor.py app/graph/rag_graph.py app/db/models.py app/api/routes.py`
Expected: 无错误（若有格式问题按 ruff 建议修复后重跑）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/tests/test_citation_e2e.py
git commit -m "test(citation): end-to-end source enrichment coverage"
```

---

## Self-Review

**1. Spec coverage（对照 spec 各节）：**
- §3.1 目标（char_start/end、heading_path、chunk_index）→ Task 1（计算）+ Task 2（存储）+ Task 4/5（透出）✅
- §3.2 独立可单测的 chunk_locator 单元 → Task 1 ✅
- §3.3 数据流（游标推进 offset、heading 栈回溯）→ Task 1 实现 + 测试 ✅
- §3.4 Chunk 新增 3 nullable 列 + 迁移 → Task 2 ✅；检索层透传（复用 KB 校验 SQL）→ Task 4 ✅；SourceResponse 可选字段 → Task 5 ✅
- §3.5 错误处理（offset 未命中降级、heading 异常整篇降级、超长末尾截断）→ Task 1 实现 + 测试 `test_split_not_found_yields_none`/`test_oversized_heading_truncated_from_end` ✅
- §3.6 测试（markdown/纯文本/重复内容/超长 heading/找不到；集成；存量降级回归）→ Task 1 + Task 4（降级）+ Task 6（e2e）✅

**2. Placeholder scan：** 无 TBD/TODO；每个改代码步骤均给出完整代码；迁移/命令均为可执行实参。✅（Task 5 Step 5 对 `document_title` 表达式标注"保持现有写法"，因该行是既有代码、非本计划新增，属有意保留而非占位。）

**3. Type consistency：**
- `locate(content, splits) -> list[LocatorInfo]`：Task 1 定义，Task 3 以 `locate as locate_chunks` 调用，键 `char_start/char_end/heading_path` 一致 ✅
- `Chunk.char_start/char_end/heading_path`：Task 2 定义，Task 4 查询列名一致 ✅
- source dict 键 `chunk_index/char_start/char_end/heading_path`：Task 4 `format_sources` 产出 → Task 5 `source.get(...)` 消费，命名一致 ✅
- `SourceResponse` 字段名与 source dict 键一致 ✅

无问题。
