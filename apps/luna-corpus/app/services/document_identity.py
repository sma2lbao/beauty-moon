"""文档身份解析与正文内容 hash。

变更检测的纯逻辑单元：不做任何写操作，只负责
「算 hash」与「按身份键找已有文档」。
"""
import enum
import hashlib

from sqlalchemy.orm import Session

from app.db.models import Document


class ChangeType(str, enum.Enum):
    """一次写入相对已有文档的变更类型。"""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def compute_content_hash(text: str) -> str:
    """计算文档正文的 SHA-256 hex（UTF-8 编码）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_document_identity(
    db: Session,
    knowledge_base_id: str,
    *,
    external_id: str | None = None,
    original_name: str | None = None,
) -> Document | None:
    """在同一知识库内按身份键匹配已有文档。

    优先级：external_id（若提供）> original_name（匹配 title，多条取
    updated_at 最新）。均未命中返回 None。
    """
    if external_id:
        return (
            db.query(Document)
            .filter(
                Document.knowledge_base_id == knowledge_base_id,
                Document.external_id == external_id,
            )
            .first()
        )
    if original_name:
        return (
            db.query(Document)
            .filter(
                Document.knowledge_base_id == knowledge_base_id,
                Document.title == original_name,
            )
            .order_by(Document.updated_at.desc())
            .first()
        )
    return None