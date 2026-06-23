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

## Tenant and knowledge-base context

P0-M3 adds workspace-scoped RBAC enforcement to protected corpus routes. Protected routes require the P0-M2 resource context headers plus temporary request identity:

```http
X-User-Id: <user-id>
X-Tenant-Id: <tenant-id>
X-Workspace-Id: <workspace-id>
X-Knowledge-Base-Id: <knowledge-base-id>
```

`X-User-Id` is temporary request identity for development and internal calls. It is not authentication and is not a production security credential.

Seeded roles are stored in the database:

- `workspace_admin`: all workspace, knowledge-base, document, conversation, and QA permissions.
- `kb_editor`: read knowledge-base metadata, read/write/delete documents, read/write/delete conversations, and query QA.
- `kb_reader`: read workspace and knowledge-base metadata, read documents, read conversations, and query QA.

Seeded permissions include `workspace:read`, `workspace:manage`, `knowledge_base:read`, `knowledge_base:manage`, `document:read`, `document:write`, `document:delete`, `conversation:read`, `conversation:write`, `conversation:delete`, and `qa:query`.

Create the tenant and workspace hierarchy first:

```bash
POST /api/v1/tenants
POST /api/v1/workspaces
POST /api/v1/knowledge-bases
```

`POST /api/v1/tenants` and `POST /api/v1/workspaces` remain bootstrap-only setup endpoints and do not require `X-User-Id`. `GET /api/v1/tenants` and `GET /api/v1/workspaces` are scoped to the active workspaces where the current user has membership.

Requests using a document or conversation from another knowledge base still return `404`. Requests from users without the required workspace membership or permission return `403`.

## Local development

Start the API from the repository root:

```bash
pnpm nx run luna-corpus:serve
```

The API listens on `API_HOST` and `API_PORT` from `.env`.

## Tests

Run the app test suite through Nx:

```bash
pnpm nx run luna-corpus:test
```

## Production startup rule

Run `pnpm nx run luna-corpus:db-migrate` before starting the API. The API startup path is not responsible for creating production tables.
