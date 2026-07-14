"""成本模块 RBAC 权限与配置开关。"""
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, PermissionSlug, RoleSlug
from app.core.config import get_settings


def test_cost_permission_slugs_defined():
    assert PermissionSlug.COST_MANAGE == "cost:manage"
    assert PermissionSlug.COST_READ == "cost:read"


def test_workspace_admin_has_both_cost_permissions():
    perms = DEFAULT_ROLE_PERMISSIONS[RoleSlug.WORKSPACE_ADMIN]
    assert PermissionSlug.COST_MANAGE in perms
    assert PermissionSlug.COST_READ in perms


def test_kb_editor_has_read_only():
    perms = DEFAULT_ROLE_PERMISSIONS[RoleSlug.KB_EDITOR]
    assert PermissionSlug.COST_READ in perms
    assert PermissionSlug.COST_MANAGE not in perms


def test_kb_reader_has_no_cost_permissions():
    perms = DEFAULT_ROLE_PERMISSIONS[RoleSlug.KB_READER]
    assert PermissionSlug.COST_READ not in perms
    assert PermissionSlug.COST_MANAGE not in perms


def test_cost_enforcement_enabled_defaults_true():
    assert get_settings().cost_enforcement_enabled is True
