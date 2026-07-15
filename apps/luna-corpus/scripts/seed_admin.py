"""Seed the first admin user with a workspace_admin role.

Usage:
    uv run python scripts/seed_admin.py \
        --email admin@example.com --password 'secret' \
        --display-name Admin --workspace-id <workspace_id>

This is the only path that creates a user without an existing admin,
used to break the bootstrap cycle. All other users go through POST /api/v1/users.
"""
import argparse

from app.auth.password import hash_password
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, RoleSlug
from app.db.database import SessionLocal
from app.db.models import Permission, Role, User, WorkspaceMembership


def _ensure_admin_role(session) -> Role:
    role = session.query(Role).filter(Role.slug == RoleSlug.WORKSPACE_ADMIN).first()
    if role:
        return role
    permissions = []
    for slug in DEFAULT_ROLE_PERMISSIONS[RoleSlug.WORKSPACE_ADMIN]:
        perm = session.query(Permission).filter(Permission.slug == slug).first()
        if not perm:
            perm = Permission(name=slug, slug=slug, description=slug)
            session.add(perm)
        permissions.append(perm)
    role = Role(
        name="Workspace Admin",
        slug=RoleSlug.WORKSPACE_ADMIN,
        is_system=True,
        permissions=permissions,
    )
    session.add(role)
    return role


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--workspace-id", required=True)
    args = parser.parse_args()

    if len(args.password) < 8:
        raise SystemExit("Password must be at least 8 characters")

    session = SessionLocal()
    try:
        if session.query(User).filter(User.email == args.email).first():
            raise SystemExit(f"User already exists: {args.email}")
        role = _ensure_admin_role(session)
        user = User(
            email=args.email,
            display_name=args.display_name,
            hashed_password=hash_password(args.password),
        )
        membership = WorkspaceMembership(
            user=user, workspace_id=args.workspace_id, roles=[role]
        )
        session.add(membership)
        session.commit()
        print(f"Created admin user {args.email} ({user.id})")
    finally:
        session.close()


if __name__ == "__main__":
    main()
