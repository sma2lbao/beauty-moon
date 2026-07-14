"""Seeded RBAC role and permission constants."""


class PermissionSlug:
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_MANAGE = "workspace:manage"
    KNOWLEDGE_BASE_READ = "knowledge_base:read"
    KNOWLEDGE_BASE_MANAGE = "knowledge_base:manage"
    DOCUMENT_READ = "document:read"
    DOCUMENT_WRITE = "document:write"
    DOCUMENT_DELETE = "document:delete"
    CONVERSATION_READ = "conversation:read"
    CONVERSATION_WRITE = "conversation:write"
    CONVERSATION_DELETE = "conversation:delete"
    QA_QUERY = "qa:query"
    QA_FEEDBACK = "qa:feedback"
    QA_REVIEW = "qa:review"
    PROMPT_MANAGE = "prompt:manage"
    COST_MANAGE = "cost:manage"
    COST_READ = "cost:read"


class RoleSlug:
    WORKSPACE_ADMIN = "workspace_admin"
    KB_EDITOR = "kb_editor"
    KB_READER = "kb_reader"


DEFAULT_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    RoleSlug.WORKSPACE_ADMIN: (
        PermissionSlug.WORKSPACE_READ,
        PermissionSlug.WORKSPACE_MANAGE,
        PermissionSlug.KNOWLEDGE_BASE_READ,
        PermissionSlug.KNOWLEDGE_BASE_MANAGE,
        PermissionSlug.DOCUMENT_READ,
        PermissionSlug.DOCUMENT_WRITE,
        PermissionSlug.DOCUMENT_DELETE,
        PermissionSlug.CONVERSATION_READ,
        PermissionSlug.CONVERSATION_WRITE,
        PermissionSlug.CONVERSATION_DELETE,
        PermissionSlug.QA_QUERY,
        PermissionSlug.QA_FEEDBACK,
        PermissionSlug.QA_REVIEW,
        PermissionSlug.PROMPT_MANAGE,
        PermissionSlug.COST_MANAGE,
        PermissionSlug.COST_READ,
    ),
    RoleSlug.KB_EDITOR: (
        PermissionSlug.WORKSPACE_READ,
        PermissionSlug.KNOWLEDGE_BASE_READ,
        PermissionSlug.DOCUMENT_READ,
        PermissionSlug.DOCUMENT_WRITE,
        PermissionSlug.DOCUMENT_DELETE,
        PermissionSlug.CONVERSATION_READ,
        PermissionSlug.CONVERSATION_WRITE,
        PermissionSlug.CONVERSATION_DELETE,
        PermissionSlug.QA_QUERY,
        PermissionSlug.QA_FEEDBACK,
        PermissionSlug.QA_REVIEW,
        PermissionSlug.PROMPT_MANAGE,
        PermissionSlug.COST_READ,
    ),
    RoleSlug.KB_READER: (
        PermissionSlug.WORKSPACE_READ,
        PermissionSlug.KNOWLEDGE_BASE_READ,
        PermissionSlug.DOCUMENT_READ,
        PermissionSlug.CONVERSATION_READ,
        PermissionSlug.QA_QUERY,
        PermissionSlug.QA_FEEDBACK,
    ),
}
