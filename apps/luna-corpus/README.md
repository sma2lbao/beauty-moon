# luna-corpus

RAG-based Q&A knowledge base API built with FastAPI, SQLAlchemy, Chroma, LangGraph, and configurable LLM providers.

## Prerequisites

- Python managed by `uv`
- Workspace package manager available from the repository root
- MySQL database reachable by `DATABASE_URL`
- Chroma storage path or service configuration
- Ollama, Ark, or Doubao credentials depending on `LLM_PROVIDER`

## Environment

Copy the example file before running locally:

```bash
cp apps/luna-corpus/.env.example apps/luna-corpus/.env
```

Important runtime settings:

- `APP_ENV=development` for local development.
- `APP_ENV=production` for production deployments.
- `AUTO_CREATE_TABLES=false` is the standard path because schema changes are managed by Alembic.
- `CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:4200` configures allowed browser origins.

Production must keep `AUTO_CREATE_TABLES=false` and must set explicit CORS origins. Wildcard CORS origins are rejected in production.

## Database migrations

Run migrations from the repository root through Nx:

```bash
pnpm nx run luna-corpus:db-migrate
```

Create a new autogeneration revision after changing SQLAlchemy models:

```bash
pnpm nx run luna-corpus:db-revision
```

Review generated revisions before committing them.

## Authentication

All protected endpoints require a JWT access token in the `Authorization: Bearer <token>` header. The token identifies the caller; forged or missing tokens return `401`. Resource-scope headers still select the knowledge-base context:

```http
Authorization: Bearer <access-token>
X-Tenant-Id: <tenant-id>
X-Workspace-Id: <workspace-id>
X-Knowledge-Base-Id: <knowledge-base-id>
```

There is no `X-User-Id` trust anymore — the caller identity is derived from the verified access token only.

Production must set a strong `JWT_SECRET_KEY`; the app refuses to start with an empty or default secret.

### Bootstrap the first admin

There is no public registration. The first admin is created with the seed script, which also binds a `workspace_admin` role:

```bash
cd apps/luna-corpus
uv run python scripts/seed_admin.py \
  --email admin@example.com --password 'change-me' \
  --display-name Admin --workspace-id <workspace_id>
```

All subsequent users are created by an admin through `POST /api/v1/users` (requires `workspace:manage`). The new user is bound to the admin's active workspace with the requested `role_slug` (`workspace_admin`, `kb_editor`, or `kb_reader`; defaults to `kb_reader`):

```bash
curl -X POST http://localhost:8000/api/v1/users \
  -H 'Authorization: Bearer <admin-access-token>' \
  -H 'X-Tenant-Id: ...' -H 'X-Workspace-Id: ...' -H 'X-Knowledge-Base-Id: ...' \
  -H 'Content-Type: application/json' \
  -d '{"email":"member@example.com","display_name":"Member","password":"pw123456","role_slug":"kb_reader"}'
```

### Login flow

```bash
# 1. Login -> access_token + refresh_token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"change-me"}'

# 2. Call protected endpoints with the access token + resource headers
curl http://localhost:8000/api/v1/knowledge-bases \
  -H 'Authorization: Bearer <access_token>' \
  -H 'X-Tenant-Id: ...' -H 'X-Workspace-Id: ...' -H 'X-Knowledge-Base-Id: ...'

# 3. Refresh when the access token expires (rotates the refresh token)
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<refresh_token>"}'

# 4. Logout (revoke the refresh token)
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<refresh_token>"}'
```

## Tenant and knowledge-base context

Protected corpus routes enforce workspace-scoped RBAC. Beyond the `Authorization` bearer token, they require the resource context headers `X-Tenant-Id`, `X-Workspace-Id`, and `X-Knowledge-Base-Id` to select the active knowledge base.

Seeded roles are stored in the database:

- `workspace_admin`: all workspace, knowledge-base, document, conversation, QA, and cost permissions.
- `kb_editor`: read knowledge-base metadata, read/write/delete documents, read/write/delete conversations, query QA, and read cost.
- `kb_reader`: read workspace and knowledge-base metadata, read documents, read conversations, and query QA.

Create the tenant and workspace hierarchy first:

```bash
POST /api/v1/tenants
POST /api/v1/workspaces
POST /api/v1/knowledge-bases
```

`POST /api/v1/tenants` and `POST /api/v1/workspaces` now require a valid bearer token: creating a tenant is open to any authenticated user (platform setup), while creating a workspace additionally requires `workspace:manage` in the target tenant. `GET /api/v1/tenants` and `GET /api/v1/workspaces` are scoped to the workspaces where the caller has active membership.

Requests using a document or conversation from another knowledge base still return `404`. Requests from users without the required workspace membership or permission return `403`.

## Local development

Start the API from the repository root:

```bash
pnpm nx run luna-corpus:serve
```

The API listens on `API_HOST` and `API_PORT` from `.env`.

## Observability

- Structured logs (JSON in production, console otherwise) carry `request_id`, `user_id`, and `tenant_id` when available. Control with `LOG_LEVEL` and `LOG_FORMAT`.
- Prometheus metrics are exposed at `GET /metrics` (disable with `METRICS_ENABLED=false`). HTTP request counts/latency plus retrieval, embedding, LLM, and index-task timings are tracked.
- `GET /api/v1/health` reports per-component status for `database`, `vectorstore`, and the configured `llm_provider`; overall status is `degraded` if the database or vector store is down.

## Tests

Run the app test suite through Nx:

```bash
pnpm nx run luna-corpus:test
```

## Production startup rule

Run `pnpm nx run luna-corpus:db-migrate` before starting the API. The API startup path is not responsible for creating production tables.
