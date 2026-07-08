"""元数据字段定义 ORM。"""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base
from app.metadata.schema import FieldType


class MetadataFieldDefinition(Base):
    """知识库级元数据字段定义。"""

    __tablename__ = "metadata_field_definitions"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "key"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[FieldType] = mapped_column(Enum(FieldType), nullable=False)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_facetable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
