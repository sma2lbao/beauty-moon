"""Config / permission / audit wiring for quality evaluation."""
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, PermissionSlug, RoleSlug
from app.core.config import get_settings
from app.security.audit import AuditAction


def test_sample_rate_default():
    assert get_settings().quality_eval_sample_rate == 0.1


def test_qa_feedback_permission_seeded():
    assert PermissionSlug.QA_FEEDBACK == "qa:feedback"
    for role in (RoleSlug.WORKSPACE_ADMIN, RoleSlug.KB_EDITOR, RoleSlug.KB_READER):
        assert PermissionSlug.QA_FEEDBACK in DEFAULT_ROLE_PERMISSIONS[role]


def test_qa_feedback_audit_action():
    assert AuditAction.QA_FEEDBACK.value == "qa.feedback"
