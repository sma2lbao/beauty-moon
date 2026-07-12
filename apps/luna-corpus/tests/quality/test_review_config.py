"""Config / permission / audit wiring for the review loop."""
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, PermissionSlug, RoleSlug
from app.core.config import get_settings
from app.security.audit import AuditAction


def test_review_score_threshold_default():
    assert get_settings().quality_review_score_threshold == 0.6


def test_qa_review_permission_seeded():
    assert PermissionSlug.QA_REVIEW == "qa:review"
    for role in (RoleSlug.WORKSPACE_ADMIN, RoleSlug.KB_EDITOR):
        assert PermissionSlug.QA_REVIEW in DEFAULT_ROLE_PERMISSIONS[role]
    assert PermissionSlug.QA_REVIEW not in DEFAULT_ROLE_PERMISSIONS[RoleSlug.KB_READER]


def test_qa_review_audit_actions():
    assert AuditAction.QA_REVIEW_RESOLVE.value == "qa.review_resolve"
    assert AuditAction.QA_REVIEW_DISMISS.value == "qa.review_dismiss"
