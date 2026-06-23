# P0-M3 RBAC Enforcement Design

## Goal

P0-M3 adds request identity and workspace-scoped RBAC enforcement to `apps/luna-corpus`. It builds on P0-M2 tenant/workspace/knowledge-base context by requiring a temporary `X-User-Id` header for protected corpus APIs and checking that the user has an active workspace membership with the required permission.

This milestone does not implement production authentication. `X-User-Id` is temporary request identity, not proof of authentication.

## Scope

P0-M3 protects:

- Tenant/workspace/knowledge-base read and knowledge-base management APIs.
- Document APIs.
- QA APIs.
- Conversation APIs.

P0-M3 does not protect:

- `agent_routes`.
- `/health`.
- Bootstrap creation for tenants and workspaces.

P0-M3 does not implement:

- JWT, OIDC, login, session cookies, password auth, or API keys.
- Custom role management APIs.
- Knowledge-base-specific grants.
- Tenant-wide roles.
- System-level admin users.

## Architecture

P0-M2 request context remains responsible for validating resource context:

- `X-Tenant-Id` is present and identifies an existing tenant.
- `X-Workspace-Id` is present and identifies an existing workspace.
- `X-Knowledge-Base-Id` is present and identifies an existing knowledge base.
- The workspace belongs to the tenant.
- The knowledge base belongs to the workspace.

P0-M3 adds authenticated request context on top of that resource context:

- `X-User-Id` is present.
- The user exists and is active.
- The user has an active membership in the requested workspace.
- The membership has one or more seeded roles.
- The role permissions include the permission required by the route.

The effective access model is:

```text
User
  -> WorkspaceMembership
    -> Role(s)
      -> Permission(s)
        -> applies to all KnowledgeBase resources under that workspace
```

A user with membership in workspace A cannot access workspace B by sending workspace B headers, even if they know the tenant, workspace, or knowledge-base IDs.

## Data Model

### User

`User` represents an application identity.

Fields:

- `id`
- `email`
- `display_name`
- `is_active`
- `created_at`
- `updated_at`

Constraints:

- `email` is unique.
- Inactive users fail authorization with `403 Forbidden`.

P0-M3 does not add password hashes, OIDC subject fields, avatar fields, or profile metadata.

### WorkspaceMembership

`WorkspaceMembership` connects a user to one workspace.

Fields:

- `id`
- `user_id`
- `workspace_id`
- `is_active`
- `created_at`
- `updated_at`

Constraints:

- `(user_id, workspace_id)` is unique.
- Inactive memberships fail authorization with `403 Forbidden`.

### Role

`Role` stores seeded system roles in the database.

Fields:

- `id`
- `name`
- `slug`
- `description`
- `is_system`
- `created_at`
- `updated_at`

Seeded roles:

- `workspace_admin`
- `kb_editor`
- `kb_reader`

P0-M3 does not expose APIs to create, update, or delete roles.

### Permission

`Permission` stores seeded permission names in the database.

Fields:

- `id`
- `name`
- `slug`
- `description`

Seeded permissions:

- `workspace:read`
- `workspace:manage`
- `knowledge_base:read`
- `knowledge_base:manage`
- `document:read`
- `document:write`
- `document:delete`
- `conversation:read`
- `conversation:write`
- `conversation:delete`
- `qa:query`

### Join Tables

`role_permissions` maps roles to permissions.

`workspace_membership_roles` maps workspace memberships to roles.

Default role mappings:

```text
workspace_admin:
  workspace:read
  workspace:manage
  knowledge_base:read
  knowledge_base:manage
  document:read
  document:write
  document:delete
  conversation:read
  conversation:write
  conversation:delete
  qa:query

kb_editor:
  workspace:read
  knowledge_base:read
  document:read
  document:write
  document:delete
  conversation:read
  conversation:write
  conversation:delete
  qa:query

kb_reader:
  workspace:read
  knowledge_base:read
  document:read
  conversation:read
  qa:query
```

## Authorization Dependencies

The existing resource context dependency should remain available for pure tenant/workspace/knowledge-base validation. P0-M3 adds a permission dependency shaped like:

```python
require_permission("document:read")
require_permission("document:write")
require_permission("qa:query")
```

The dependency returns an authenticated context containing:

- `user`
- `tenant`
- `workspace`
- `knowledge_base`
- `membership`
- effective permissions

Error semantics:

- Missing `X-User-Id`: `400 Bad Request`.
- User not found: `401 Unauthorized`.
- Inactive user: `403 Forbidden`.
- Missing workspace membership: `403 Forbidden`.
- Inactive membership: `403 Forbidden`.
- Missing required permission: `403 Forbidden`.
- Missing or mismatched tenant/workspace/knowledge-base context: existing P0-M2 `404 Not Found` behavior.

## API Enforcement

Bootstrap endpoints remain outside RBAC:

- `POST /tenants`
- `POST /workspaces`

Read/list tenant and workspace endpoints become user-scoped:

- `GET /tenants`: requires `X-User-Id` and returns tenants containing workspaces where the user has active membership.
- `GET /workspaces`: requires `X-User-Id` and returns workspaces where the user has active membership, optionally filtered by `tenant_id`.

Knowledge-base endpoints:

- `GET /knowledge-bases`: `knowledge_base:read`; returns knowledge bases in the authorized workspace.
- `POST /knowledge-bases`: `knowledge_base:manage`.

Document endpoints:

- `POST /documents`: `document:write`.
- `GET /documents`: `document:read`.
- `GET /documents/{document_id}`: `document:read`.
- `DELETE /documents/{document_id}`: `document:delete`.
- `POST /documents/{document_id}/process`: `document:write`.

QA endpoints:

- `POST /qa/query`: `qa:query`.
- `POST /qa/stream`: `qa:query`.

Conversation endpoints:

- `POST /conversations`: `conversation:write`.
- `GET /conversations`: `conversation:read`.
- `GET /conversations/{conversation_id}`: `conversation:read`.
- `GET /conversations/{conversation_id}/messages`: `conversation:read`.
- `DELETE /conversations/{conversation_id}`: `conversation:delete`.
- `POST /conversations/{conversation_id}/clear`: `conversation:write`.
- `POST /qa/multi-turn`: `qa:query` and `conversation:write`.
- `POST /qa/multi-turn/stream`: `qa:query` and `conversation:write`.

## Testing Strategy

### Model Tests

Cover:

- User email uniqueness.
- Workspace membership uniqueness on `(user_id, workspace_id)`.
- Role slug uniqueness.
- Permission slug uniqueness.
- Role-permission relationships.
- Membership-role relationships.
- Inactive users and memberships can exist but fail authorization.

### Migration Tests

Cover:

- The P0-M3 migration exists.
- The migration creates `users`, `workspace_memberships`, `roles`, `permissions`, `role_permissions`, and `workspace_membership_roles`.
- The migration seeds all default roles and permissions.
- The seeded role-permission mapping includes reader, editor, and admin permissions.
- Downgrade removes the new tables in dependency-safe order.

### Authorization Tests

Cover:

- Missing `X-User-Id` returns 400.
- Unknown user returns 401.
- Inactive user returns 403.
- Missing workspace membership returns 403.
- Inactive membership returns 403.
- Missing required permission returns 403.
- Authorized membership returns authenticated context.
- A user authorized for workspace A cannot access workspace B.

### API Tests

Cover role behavior:

- `kb_reader` can list/get documents, query QA, and read conversations.
- `kb_reader` cannot create/delete documents, create/clear/delete conversations, or create knowledge bases.
- `kb_editor` can read/write/delete documents, query QA, and write conversations.
- `kb_editor` cannot manage knowledge bases.
- `workspace_admin` can manage knowledge bases and perform document, conversation, and QA operations.
- `GET /workspaces` and `GET /knowledge-bases` only return resources visible to the current user.
- `POST /tenants` and `POST /workspaces` remain bootstrap-only and do not require `X-User-Id`.

### Regression Tests

Keep P0-M2 isolation guarantees:

- Authorized users still cannot access resources through mismatched tenant/workspace/knowledge-base header combinations.
- RAG and vectorstore retrieval remain filtered by `knowledge_base_id`.
- Conversations remain scoped by knowledge base.

## Documentation

Update `apps/luna-corpus/README.md` to describe:

- Temporary `X-User-Id` request identity.
- Required P0-M2 context headers for protected corpus routes.
- Seeded roles and permissions.
- Bootstrap-only tenant/workspace creation.
- The fact that P0-M3 is authorization enforcement, not production authentication.
