"""SQLAlchemy models for documents and chunks."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class ContentStatus(str, enum.Enum):
    """Document processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


class FileUploadStatus(str, enum.Enum):
    """File upload processing status."""

    UPLOADED = "uploaded"
    PARSED = "parsed"
    ERROR = "error"


class ContentType(str, enum.Enum):
    """Type of content in a chunk."""

    TEXT = "text"
    TABLE = "table"
    CODE = "code"


class MessageRole(str, enum.Enum):
    """Role of message sender."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AuditResult(str, enum.Enum):
    """Outcome of an audited action."""

    SUCCESS = "success"
    FAILURE = "failure"


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        CHAR(36),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        CHAR(36),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

workspace_membership_roles = Table(
    "workspace_membership_roles",
    Base.metadata,
    Column(
        "membership_id",
        CHAR(36),
        ForeignKey("workspace_memberships.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        CHAR(36),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class User(Base):
    """Application identity resolved from temporary request headers."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    workspace_memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership", back_populates="user", cascade="all, delete-orphan"
    )


class Permission(Base):
    """Seeded permission that can be assigned to roles."""

    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    roles: Mapped[list["Role"]] = relationship(
        "Role", secondary=role_permissions, back_populates="permissions"
    )


class Role(Base):
    """Seeded role that grants permissions to workspace memberships."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    permissions: Mapped[list[Permission]] = relationship(
        "Permission", secondary=role_permissions, back_populates="roles"
    )
    workspace_memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership",
        secondary=workspace_membership_roles,
        back_populates="roles",
    )


class WorkspaceMembership(Base):
    """User membership in a workspace."""

    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="workspace_memberships")
    workspace: Mapped["Workspace"] = relationship(
        "Workspace", back_populates="memberships"
    )
    roles: Mapped[list[Role]] = relationship(
        "Role", secondary=workspace_membership_roles, back_populates="workspace_memberships"
    )


class Tenant(Base):
    """Tenant boundary for workspaces."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    workspaces: Mapped[list["Workspace"]] = relationship(
        "Workspace", back_populates="tenant", cascade="all, delete-orphan"
    )


class Workspace(Base):
    """Workspace within a tenant."""

    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="workspaces")
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        "KnowledgeBase", back_populates="workspace", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership", back_populates="workspace", cascade="all, delete-orphan"
    )


class KnowledgeBase(Base):
    """Knowledge base within a workspace."""

    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("workspace_id", "slug"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(
        "Workspace", back_populates="knowledge_bases"
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    file_uploads: Mapped[list["FileUpload"]] = relationship(
        "FileUpload", back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class FileUpload(Base):
    """Uploaded file record."""

    __tablename__ = "file_uploads"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[FileUploadStatus] = mapped_column(
        Enum(FileUploadStatus), default=FileUploadStatus.UPLOADED
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    knowledge_base: Mapped[KnowledgeBase] = relationship(
        "KnowledgeBase", back_populates="file_uploads"
    )
    document: Mapped["Document"] = relationship(
        "Document", back_populates="file", uselist=False
    )


class Document(Base):
    """Document model."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("file_uploads.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    doc_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    has_tables: Mapped[bool] = mapped_column(Boolean, default=False)
    has_code: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus), default=ContentStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="documents"
    )
    file: Mapped["FileUpload | None"] = relationship(
        "FileUpload", back_populates="document"
    )


class Chunk(Base):
    """Chunk model for document segments."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[ContentType] = mapped_column(
        Enum(ContentType), default=ContentType.TEXT
    )
    chunk_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")


class Conversation(Base):
    """Conversation session model."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="conversations"
    )


class TaskType(str, enum.Enum):
    """Type of background ingestion task."""

    DOCUMENT_INDEX = "document_index"


class TaskStatus(str, enum.Enum):
    """Status of a background ingestion task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IngestionTask(Base):
    """Background ingestion task tracking."""

    __tablename__ = "ingestion_tasks"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    type: Mapped[TaskType] = mapped_column(Enum(TaskType), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False
    )
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    """Message in a conversation."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )


class AuditLog(Base):
    """Durable, queryable audit trail for security-relevant actions."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    knowledge_base_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result: Mapped[AuditResult] = mapped_column(Enum(AuditResult), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# 注册元数据字段定义表到同一 Base.metadata（供建表 / alembic 发现）。
from app.metadata.models import MetadataFieldDefinition  # noqa: E402,F401

