# Vector Store Operations

## Current Strategy

`luna-corpus` stores document chunk embeddings in Chroma. P0-M4 keeps one logical collection and enforces knowledge-base isolation with mandatory metadata filtering.

Default collection name:

```text
document_chunks
```

Every vector record must include this metadata:

- `chunk_id`
- `document_id`
- `knowledge_base_id`

`knowledge_base_id` is required for retrieval isolation. Search code must always filter by the current request's knowledge base.

## Collection Naming

Use a stable collection name per environment. The default is `document_chunks`.

Recommended environment patterns:

- Local development: local Chroma instance with `document_chunks`.
- Test: temporary Chroma data directory or isolated test collection name.
- Staging: dedicated Chroma server or collection name separate from production.
- Production: dedicated Chroma server or volume with `document_chunks`.

Do not point development, test, staging, and production at the same Chroma collection.

P0-M4 does not use collection-per-tenant or collection-per-knowledge-base. If that changes later, it should be handled as a migration with a rebuild plan.

## Local Chroma Backup

For local `PersistentClient` deployments:

1. Stop writes to the application.
2. Back up the SQL database.
3. Copy the configured `chroma_data_dir` to backup storage.
4. Record the application version, embedding model, collection name, and backup timestamp.
5. Resume writes.

The SQL backup and Chroma directory copy should represent the same point in time. If they do not, restore may contain chunks that exist in one system but not the other.

## Chroma Server Backup

For Chroma Server deployments:

1. Stop writes or put the application into read-only mode.
2. Back up the SQL database.
3. Snapshot the Chroma server storage volume or use the backup procedure supported by the deployment platform.
4. Record Chroma server version, collection name, embedding model, and backup timestamp.
5. Resume writes.

Prefer platform volume snapshots for production server deployments. Coordinate Chroma snapshots with SQL backups.

## Restore

Restore SQL and Chroma from matching backups when possible.

If Chroma backup is missing, stale, or suspected corrupt, treat SQL as the source of truth and rebuild the vector index from stored chunks.

## Rebuild Strategy

The SQL `Document` and `Chunk` tables are the source of truth. A rebuild should:

1. Create or reset the target Chroma collection.
2. Read chunks from SQL by knowledge base or workspace.
3. Recompute embeddings with the configured embedding model.
4. Add vectors with the original `chunk_id`, `document_id`, and `knowledge_base_id` metadata.
5. Verify a sample query per knowledge base only returns that knowledge base.
6. Switch traffic to the rebuilt collection or server.

P0-M4 documents this strategy but does not implement a rebuild API, CLI, or background job.

## Future Backends

Future pgvector, Qdrant, Milvus, or other vector store implementations should implement the same backend operations:

- add chunks with metadata;
- search with mandatory `knowledge_base_id` filtering;
- delete chunks by chunk id;
- expose a health check when possible.

RAG graph and agent code should not depend on Chroma-specific APIs.
