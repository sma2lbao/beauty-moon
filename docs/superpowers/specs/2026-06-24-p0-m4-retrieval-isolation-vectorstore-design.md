# P0-M4 Retrieval Isolation and Vector Store Productionization Design

## Goal

P0-M4 makes every retrieval path obey the tenant/workspace/knowledge-base boundary and prepares the vector store layer for production deployment. It closes the P0-M3 gap where `agent_routes` remained outside RBAC, hardens source validation after vector search, and introduces a backend abstraction for local Chroma and Chroma Server.

P0-M4 does not replace Chroma with pgvector, Qdrant, Milvus, or another vector database. It keeps the existing single Chroma collection strategy and enforces isolation with mandatory `knowledge_base_id` metadata filters plus database source validation.

## Scope

P0-M4 protects and productionizes:

- All `/api/v1/agent/*` endpoints.
- RAG graph retrieval for non-streaming, streaming, multi-turn, and multi-turn streaming QA.
- Agent `rag_search` tool retrieval.
- Vector store initialization for local Chroma and Chroma Server.
- Source validation before prompt construction and API responses.
- Vector store operations documentation for backups, restore/rebuild, and collection naming.

P0-M4 does not implement:

- pgvector, Qdrant, Milvus, Weaviate, Pinecone, or multi-backend storage.
- Collection-per-tenant or collection-per-knowledge-base migration.
- Rebuild-index API endpoints, background jobs, or CLI commands.
- Production authentication beyond the existing temporary `X-User-Id` header model.
- Knowledge-base-specific grants beyond the P0-M3 workspace membership model.

## Architecture

P0-M4 uses four defenses in sequence:

1. **Request context enforcement**: every agent endpoint uses the existing tenant/workspace/knowledge-base and RBAC dependencies.
2. **Scoped tool creation**: agent RAG tools are created per request and capture the current `knowledge_base_id` in a closure.
3. **Mandatory vector filter**: vector search requires `knowledge_base_id` and sends it as a Chroma metadata filter.
4. **Source validation**: RAG code verifies returned `document_id` values belong to the current knowledge base before using them in prompts or response sources.

The effective retrieval boundary is:

```text
HTTP request headers
  -> RequestContext + AuthenticatedRequestContext
    -> current knowledge_base_id
      -> RAG graph or scoped agent tool
        -> search_vectorstore(..., knowledge_base_id=current knowledge_base_id)
          -> metadata-filtered Chroma query
            -> document_id source validation against SQL database
              -> prompt context and response sources
```

This design keeps P0-M2's single collection decision. Chroma collection `document_chunks` remains shared, but unscoped search becomes a development error instead of a valid call path.

## Agent API Enforcement

`apps/luna-corpus/app/api/agent_routes.py` should use the existing `require_permission(...)` dependency for every endpoint.

Permission mapping:

| Endpoint | Permission |
| --- | --- |
| `POST /api/v1/agent/query` | `qa:query` |
| `POST /api/v1/agent/stream` | `qa:query` |
| `GET /api/v1/agent/tools` | `knowledge_base:read` |
| `GET /api/v1/agent/modes` | `knowledge_base:read` |
| `POST /api/v1/agent/tools` | `knowledge_base:manage` |

This means:

- Anonymous users cannot access agent endpoints.
- Readers can run agent QA and inspect available tool metadata.
- Editors can run agent QA, but cannot register tools unless they also have `knowledge_base:manage`.
- Workspace admins can register tools.
- Tenant/workspace/knowledge-base mismatches continue to fail in the P0-M2 context layer.

## Scoped Agent RAG Tool

`apps/luna-corpus/app/agent/tools/rag_search.py` should expose a factory such as:

```python
create_rag_search_tool(knowledge_base_id: str) -> Tool
```

The returned tool:

- Keeps the existing public tool name: `rag_search`.
- Keeps tool parameters limited to `query` and `top_k`.
- Does not expose `knowledge_base_id` in the JSON schema.
- Captures `knowledge_base_id` in the executor closure.
- Calls `search_vectorstore(query_embedding, top_k=top_k, knowledge_base_id=knowledge_base_id)`.

`agent_routes` should build a request-scoped `ToolRegistry` with:

- scoped `rag_search` tool for the current knowledge base;
- global `calculator` tool;
- global `current_time` tool;
- any persisted registered tools.

The global unscoped `rag_search_tool` should not be registered in the default agent registry. It can be removed, or retained only as a compatibility alias that fails without an explicit knowledge-base scope.

## Vector Store Backend Layer

`apps/luna-corpus/app/db/vectorstore.py` should become a façade over a backend interface while preserving existing call sites.

### Data Objects

Introduce small typed objects or dataclasses for backend boundaries:

- `VectorChunkInput`: chunk id, document id, knowledge base id, content, embedding.
- `VectorSearchResult`: chunk id, document id, content, score.

Existing function signatures may still accept dictionaries for compatibility, but backend implementations should work with normalized objects internally.

### Backend Interface

Define a protocol/interface with operations:

- `add_chunks(chunks, embeddings) -> None`
- `search(query_embedding, *, knowledge_base_id: str, top_k: int) -> list[VectorSearchResult]`
- `delete_chunks(chunk_ids: list[str]) -> None`
- optional `health_check() -> None`

`search` must require a non-empty `knowledge_base_id`. Calling the façade without a knowledge-base scope should raise a clear isolation error.

### Implementations

P0-M4 implements only:

- `ChromaLocalBackend`: uses `chromadb.PersistentClient(path=settings.chroma_data_dir)`.
- `ChromaServerBackend`: uses `chromadb.HttpClient(...)` with configured host, port, SSL, and optional headers.

Both implementations use the same collection name setting. The default remains the current collection name, `document_chunks`.

### Factory and Caching

Add a factory such as `get_vectorstore_backend()` that reads settings and returns a cached backend instance. Tests can reset or monkeypatch this factory.

The public façade remains:

- `get_vector_store()`
- `add_chunks_to_vectorstore(...)`
- `search_vectorstore(...)`
- `delete_chunks_from_vectorstore(...)`

This preserves current imports in document processing and RAG graph code while allowing future backend implementations to be added without changing callers.

## Configuration

`apps/luna-corpus/app/core/config.py` should add a vector store backend enum and settings.

Suggested fields:

- `VectorStoreBackendType.CHROMA_LOCAL = "chroma_local"`
- `VectorStoreBackendType.CHROMA_SERVER = "chroma_server"`
- `vectorstore_backend`, default `chroma_local`
- `chroma_collection_name`, default `document_chunks`
- `chroma_data_dir`, retained for local mode
- `chroma_host`, default `localhost`
- `chroma_port`, default Chroma server port
- `chroma_ssl`, default `False`
- optional simple auth/header configuration if it can be represented cleanly in existing settings style

Configuration validation should reject unsupported backend values through the enum. Backend factory errors should use explicit vector store configuration exceptions.

## Source Validation

RAG source validation should happen after vector search and before prompt construction.

Add a helper in the graph layer or a small service module that:

1. Accepts retrieved documents and current `knowledge_base_id`.
2. Extracts unique non-empty `document_id` values.
3. Queries SQL for documents whose `id` is in that set and whose `knowledge_base_id` equals the current knowledge base.
4. Keeps only retrieved results with valid document IDs.

This helper should be used by:

- `answer_question`
- `answer_question_stream`
- `answer_question_multi_turn`
- `answer_question_multi_turn_stream`

The same validated result set should feed both prompt context and response sources. If all vector results are filtered out, the graph should behave as if no documents were retrieved. It must not reveal that filtered cross-knowledge-base results existed.

The validation is intentionally at `document_id` granularity. Chunk-level validation is not required for P0-M4 because chunks already belong to documents in the SQL model, and the accepted design target is to defend source references before returning or prompting with them.

## Error Handling

Use explicit vector store errors where practical:

- `VectorStoreError`: base vector store failure.
- `VectorStoreConfigurationError`: invalid backend configuration or unsupported backend.
- `VectorStoreIsolationError`: missing or empty `knowledge_base_id` for search.

Expected behavior:

- Missing tenant/workspace/knowledge-base headers fail in existing context dependencies.
- Missing or invalid user identity fails in existing auth dependencies.
- Missing permissions fail with existing `403 Forbidden` behavior.
- Missing `knowledge_base_id` inside vector search raises `VectorStoreIsolationError` and is covered by tests.
- Chroma failures are wrapped or surfaced as `VectorStoreError`; streaming endpoints convert exceptions to error SSE events through existing generator behavior.
- Agent tool failures continue to return an error tool result string, but must not include retrieved cross-boundary content.
- Source validation filtering all results returns the normal no-document answer path.

## Operations Documentation

Add `apps/luna-corpus/docs/vectorstore-operations.md`.

It should document:

- Current collection strategy: one collection, default `document_chunks`.
- Required metadata: `chunk_id`, `document_id`, `knowledge_base_id`.
- Local Chroma backup: stop writes, copy `chroma_data_dir`, back up SQL database consistently.
- Chroma Server backup: use deployment volume snapshots or server-supported backup procedure, coordinated with SQL backup.
- Restore/rebuild strategy: SQL `Document`/`Chunk` tables are the source of truth; rebuild vectors by re-embedding chunks and re-adding them with the same metadata.
- Collection naming: keep stable names per environment; use separate Chroma instances or configured collection names for dev/test/staging/prod.
- Future backend notes: pgvector/Qdrant/Milvus can implement the same backend protocol without changing RAG graph or agent code.

The document should not describe an implemented rebuild command because P0-M4 only provides operational guidance.

## Tests

### Vector Store Tests

Extend `apps/luna-corpus/tests/db/test_vectorstore.py`:

- `search_vectorstore` without `knowledge_base_id` fails.
- Search sends Chroma `where={"knowledge_base_id": ...}`.
- Local backend initializes `PersistentClient` with `chroma_data_dir`.
- Server backend initializes `HttpClient` with configured host, port, and SSL.
- Factory selects backend from settings.
- Missing metadata remains safe to parse.
- Two knowledge bases with identical content or embeddings only return the current knowledge base.

### RAG Graph Tests

Extend graph tests:

- Retrieval passes `knowledge_base_id` into vector search.
- Source validation removes documents outside the current knowledge base.
- Non-streaming QA uses validated sources for prompt context and response sources.
- Streaming QA uses the same validation path.
- Multi-turn and multi-turn streaming use the same validation path.
- When validation removes all results, the graph follows the no-relevant-document behavior.

### Agent Tests

Extend agent tests:

- `create_rag_search_tool("kb-1")` calls vector search with `knowledge_base_id="kb-1"`.
- Tool schema does not contain `knowledge_base_id`.
- Empty results, vector errors, and formatted results preserve existing user-facing behavior.
- Default request registry uses scoped RAG tool, not a global unscoped RAG tool.

### Agent API RBAC Tests

Extend or add agent API tests:

- Anonymous calls to all `/api/v1/agent/*` endpoints are rejected.
- Reader can call query, stream, tools, and modes.
- Reader/editor cannot register tools without `knowledge_base:manage`.
- Admin can register tools.
- Cross-tenant/workspace/knowledge-base headers fail through context validation.

## Verification

Run the project tests through Nx:

```bash
npx nx run luna-corpus:test
```

If a specific failure needs investigation, use the target's underlying pytest command only for debugging. Final verification should use the Nx target.

## Acceptance Criteria Mapping

- All QA and agent retrieval APIs require authenticated knowledge-base context.
- Vector queries always include `knowledge_base_id` filters.
- Similar or identical chunks in different knowledge bases only return current-knowledge-base results.
- Sources are database-validated before prompt construction and before response output.
- Vector backend is configurable between local Chroma and Chroma Server.
- Backend structure leaves room for future pgvector/Qdrant/Milvus implementations.
- Backup, rebuild, and collection naming strategy are documented.
