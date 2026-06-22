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
