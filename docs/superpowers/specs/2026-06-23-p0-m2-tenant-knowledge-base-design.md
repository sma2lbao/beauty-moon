# P0-M2 租户与知识库上下文设计

## 背景

P0-M1 已为 `apps/luna-corpus` 建立 Alembic 迁移、运行环境配置、生产禁用自动建表、CORS 白名单和 Nx migration targets。P0-M2 在此基础上建立租户、工作区和知识库边界，让文档、对话和 RAG 检索可以按知识库隔离运行。

本设计采用“Header 上下文 + 知识库级隔离”方案：API 请求通过临时 header 传入 tenant/workspace/knowledge base 上下文，服务端校验资源层级并把文档、对话和向量检索限定在当前知识库。P0-M2 不实现登录、用户、membership、RBAC、JWT/OIDC 或异步任务。

## 目标

- 新增 `Tenant`、`Workspace`、`KnowledgeBase` SQLAlchemy 模型。
- 新增 P0-M2 Alembic migration，创建租户结构表并把现有文档/对话归属到默认知识库。
- `Document` 必须归属一个 `KnowledgeBase`。
- `Conversation` 必须归属一个 `KnowledgeBase`。
- API 通过 `X-Tenant-Id`、`X-Workspace-Id`、`X-Knowledge-Base-Id` 读取临时上下文。
- 文档创建、列表、详情、删除、处理都限定在当前知识库。
- 单轮和多轮 QA 检索都限定在当前知识库。
- Chroma chunk metadata 写入 `knowledge_base_id`，检索时使用 filter 防止串库。
- 补充模型、迁移、API、vectorstore 和文档相关测试。

## 非目标

- 不实现 User、Membership、Role、Permission、RBAC。
- 不实现 JWT/OIDC、登录、会话认证或 API key。
- 不实现文件上传、异步索引任务、任务状态机、Docker 或 Compose。
- 不把 header 上下文视为权限证明；它只是 P0-M2 的临时上下文入口。
- 不拆分 Chroma collection；P0-M2 使用现有 collection 加 metadata filter。
- 不为 Chroma 删除失败新增补偿任务或重试队列。

## 架构

P0-M2 由五个边界组成：

1. **租户模型边界**：`Tenant` 拥有多个 `Workspace`，`Workspace` 拥有多个 `KnowledgeBase`。
2. **知识库归属边界**：`Document` 和 `Conversation` 直接归属 `KnowledgeBase`；`Chunk` 通过 `Document` 继承归属，`Message` 通过 `Conversation` 继承归属。
3. **请求上下文边界**：FastAPI dependency 从 header 读取上下文并校验层级匹配。
4. **检索隔离边界**：文档处理写入 Chroma 时带 `knowledge_base_id` metadata；检索时必须传 filter。
5. **迁移边界**：P0-M2 migration 在 P0-M1 initial schema 后新增业务归属结构，并回填默认知识库以支持可重建环境升级。

## 数据模型

### Tenant

`tenants` 表代表租户边界。

字段：

- `id`: UUID string primary key。
- `name`: 非空，最大长度 255。
- `slug`: 非空，唯一，最大长度 255。
- `created_at`: 服务端默认当前时间。
- `updated_at`: 服务端默认当前时间，更新时刷新。

关系：

- `Tenant.workspaces` 一对多，级联删除 workspace。

### Workspace

`workspaces` 表代表租户下的工作区。

字段：

- `id`: UUID string primary key。
- `tenant_id`: 外键到 `tenants.id`，`ondelete="CASCADE"`。
- `name`: 非空，最大长度 255。
- `slug`: 非空，最大长度 255。
- `created_at`: 服务端默认当前时间。
- `updated_at`: 服务端默认当前时间，更新时刷新。

约束：

- `(tenant_id, slug)` 唯一。

关系：

- `Workspace.tenant` 多对一。
- `Workspace.knowledge_bases` 一对多，级联删除 knowledge base。

### KnowledgeBase

`knowledge_bases` 表代表实际文档和检索隔离单位。

字段：

- `id`: UUID string primary key。
- `workspace_id`: 外键到 `workspaces.id`，`ondelete="CASCADE"`。
- `name`: 非空，最大长度 255。
- `slug`: 非空，最大长度 255。
- `description`: 可空文本。
- `created_at`: 服务端默认当前时间。
- `updated_at`: 服务端默认当前时间，更新时刷新。

约束：

- `(workspace_id, slug)` 唯一。

关系：

- `KnowledgeBase.workspace` 多对一。
- `KnowledgeBase.documents` 一对多，级联删除 documents。
- `KnowledgeBase.conversations` 一对多，级联删除 conversations。

### Document 调整

`documents` 新增：

- `knowledge_base_id`: 非空外键到 `knowledge_bases.id`，`ondelete="CASCADE"`。

关系：

- `Document.knowledge_base` 多对一。
- `Document.chunks` 保持现有关系。

### Chunk 保持归属继承

`chunks` 不新增 tenant/workspace/knowledge base 字段，继续通过 `document_id` 继承知识库归属。

### Conversation 调整

`conversations` 新增：

- `knowledge_base_id`: 非空外键到 `knowledge_bases.id`，`ondelete="CASCADE"`。

关系：

- `Conversation.knowledge_base` 多对一。
- `Conversation.messages` 保持现有关系。

### Message 保持归属继承

`messages` 不新增 tenant/workspace/knowledge base 字段，继续通过 `conversation_id` 继承知识库归属。

## 迁移设计

新增 Alembic revision：`20260623_0002_tenant_knowledge_base_context.py`。

升级顺序：

1. 创建 `tenants`。
2. 创建 `workspaces`。
3. 创建 `knowledge_bases`。
4. 插入默认 tenant/workspace/knowledge base，用于回填已有可重建环境：
   - tenant slug: `default`
   - workspace slug: `default`
   - knowledge base slug: `default`
5. 给 `documents` 增加 `knowledge_base_id`，先允许临时 nullable。
6. 将现有 documents 回填到默认 knowledge base。
7. 将 `documents.knowledge_base_id` 改为非空并添加外键。
8. 给 `conversations` 增加 `knowledge_base_id`，先允许临时 nullable。
9. 将现有 conversations 回填到默认 knowledge base。
10. 将 `conversations.knowledge_base_id` 改为非空并添加外键。
11. 添加必要唯一约束和查询索引。

降级顺序反向执行，先移除 `conversations` 和 `documents` 上的外键/列，再删除 knowledge base、workspace、tenant 表。

## 请求上下文

新增请求上下文 dependency，例如 `get_request_context()`。

输入 header：

- `X-Tenant-Id`
- `X-Workspace-Id`
- `X-Knowledge-Base-Id`

输出对象包含：

- `tenant: Tenant`
- `workspace: Workspace`
- `knowledge_base: KnowledgeBase`

校验规则：

1. 缺少任一 header 返回 `400 Bad Request`，错误信息说明缺少哪个 header。
2. tenant/workspace/knowledge base 任一不存在返回 `404 Not Found`。
3. workspace 不属于 tenant 返回 `404 Not Found`。
4. knowledge base 不属于 workspace 返回 `404 Not Found`。

层级不匹配使用 `404`，避免暴露跨租户资源存在性。

## API 设计

### 租户结构接口

新增最小接口用于创建和发现上下文：

- `POST /api/v1/tenants`
- `GET /api/v1/tenants`
- `POST /api/v1/workspaces`
- `GET /api/v1/workspaces`
- `POST /api/v1/knowledge-bases`
- `GET /api/v1/knowledge-bases`

请求模型：

- tenant create: `name`, `slug`。
- workspace create: `tenant_id`, `name`, `slug`。
- knowledge base create: `workspace_id`, `name`, `slug`, optional `description`。

列表接口可以按父级过滤：

- `GET /workspaces?tenant_id=...`
- `GET /knowledge-bases?workspace_id=...`

这些接口不使用认证或 membership 判断。

### 文档接口调整

以下接口必须依赖 request context：

- `POST /api/v1/documents`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}`
- `DELETE /api/v1/documents/{document_id}`
- `POST /api/v1/documents/{document_id}/process`

行为：

- 创建文档时写入 `context.knowledge_base.id`。
- 列表只返回当前 knowledge base 下的 documents。
- 详情、删除、处理都加 `Document.knowledge_base_id == context.knowledge_base.id` 条件。
- 跨 knowledge base 访问 document 返回 `404 Document not found`。

### QA 接口调整

以下接口必须依赖 request context：

- `POST /api/v1/qa/query`
- `POST /api/v1/qa/stream`
- `POST /api/v1/qa/multi-turn`
- `POST /api/v1/qa/multi-turn/stream`

行为：

- 单轮 QA 把 `context.knowledge_base.id` 传入 RAG graph/vectorstore。
- 流式 QA 使用同一 knowledge base filter。
- 新建 conversation 时写入当前 knowledge base。
- 使用已有 conversation 时必须确认它属于当前 knowledge base，否则返回 `404 Conversation not found`。
- 多轮 QA 的历史读取和检索都限定当前 knowledge base。

## 向量存储设计

`add_chunks_to_vectorstore()` 输入 chunk dict 必须包含：

- `id`
- `document_id`
- `knowledge_base_id`
- `content`

写入 Chroma metadata：

- `chunk_id`
- `document_id`
- `knowledge_base_id`

`search_vectorstore()` 增加参数：

- `knowledge_base_id: str | None = None`

P0-M2 API 调用路径必须传入 `knowledge_base_id`。函数内部在调用 Chroma `collection.query()` 时传入 where filter，例如：

```python
where={"knowledge_base_id": knowledge_base_id}
```

不提供 fallback 到全局检索。若 Chroma filter 异常，QA 路径按现有异常处理返回错误。

`delete_chunks_from_vectorstore()` 继续按 chunk ids 删除，不额外按 knowledge base 过滤，因为调用方来自已校验的 document。

## 数据流

### 创建租户结构

1. 调用 `POST /tenants` 创建 tenant。
2. 调用 `POST /workspaces` 创建 workspace，并传 tenant id。
3. 调用 `POST /knowledge-bases` 创建 knowledge base，并传 workspace id。
4. 客户端保存三层 id，并在后续知识库隔离接口中作为 header 传入。

### 创建和处理文档

1. 客户端带三个 header 调用 `POST /documents`。
2. request context dependency 校验层级。
3. API 创建 document，并写入 `knowledge_base_id`。
4. 客户端调用 `POST /documents/{id}/process`。
5. API 确认 document 属于当前 knowledge base。
6. DocumentProcessor 创建 chunks。
7. 写入 Chroma 时每个 chunk metadata 带 `knowledge_base_id`。

### 单轮问答

1. 客户端带三个 header 调用 `/qa/query` 或 `/qa/stream`。
2. request context dependency 校验层级。
3. RAG graph 生成 query embedding。
4. vectorstore 使用 `knowledge_base_id` filter 检索 chunks。
5. answer response 返回当前知识库内 sources。

### 多轮问答

1. 客户端带三个 header 调用 `/qa/multi-turn` 或 `/qa/multi-turn/stream`。
2. 若未传 conversation id，创建绑定当前 knowledge base 的 conversation。
3. 若传入 conversation id，先确认 conversation 属于当前 knowledge base。
4. user/assistant messages 继续写入 messages 表。
5. 历史读取和 RAG 检索都限定当前 knowledge base。

## 错误处理

- 缺少上下文 header：`400 Bad Request`。
- tenant/workspace/knowledge base 不存在：`404 Not Found`。
- workspace 与 tenant 不匹配：`404 Not Found`。
- knowledge base 与 workspace 不匹配：`404 Not Found`。
- document 不属于当前 knowledge base：`404 Document not found`。
- conversation 不属于当前 knowledge base：`404 Conversation not found`。
- document processing 失败：沿用 `ContentStatus.ERROR`。
- Chroma filter 查询失败：沿用 QA 路径现有异常返回，不退回全局检索。
- Chroma 删除失败：P0-M2 不新增补偿任务，保持当前同步删除行为。

## 测试策略

### 模型测试

- 创建 Tenant → Workspace → KnowledgeBase 层级。
- `(tenant_id, workspace.slug)` 唯一约束生效。
- `(workspace_id, knowledge_base.slug)` 唯一约束生效。
- Document 必须归属 KnowledgeBase。
- Conversation 必须归属 KnowledgeBase。
- 删除 KnowledgeBase 级联删除 documents/chunks/conversations/messages，或通过关系配置保证子资源不可孤立。

### 迁移测试

- Alembic files 存在并包含 P0-M2 revision。
- Migration 创建 `tenants`、`workspaces`、`knowledge_bases`。
- Migration 给 `documents` 和 `conversations` 添加 `knowledge_base_id` 外键。
- Migration 包含默认 tenant/workspace/knowledge base 回填逻辑。
- Alembic env 仍能读取 `Base.metadata`。

### 请求上下文测试

- 缺少每个 header 分别返回 `400`。
- 不存在的 tenant/workspace/knowledge base 返回 `404`。
- workspace 不属于 tenant 返回 `404`。
- knowledge base 不属于 workspace 返回 `404`。
- 有效 header 返回包含三层模型的 context。

### API 测试

- Tenant/workspace/knowledge base 创建和列表接口可用。
- 创建文档写入当前 `knowledge_base_id`。
- 文档列表只返回当前 knowledge base 的文档。
- 跨 knowledge base 读取、删除、处理 document 返回 `404`。
- 创建 conversation 写入当前 `knowledge_base_id`。
- 跨 knowledge base 读取 conversation 返回 `404`。
- QA 路由把当前 `knowledge_base_id` 传入 RAG/vectorstore。

### 向量存储测试

- `add_chunks_to_vectorstore()` 写入 `knowledge_base_id` metadata。
- `search_vectorstore()` 接收 `knowledge_base_id` 并传 Chroma where filter。
- 不提供 `knowledge_base_id` 时函数仍可被低层测试调用，但 P0-M2 API 路径必须传入。
- 不要求真实 Chroma/LLM 集成测试；使用 mock 验证 filter 传递。

### 最终验证

- `pnpm nx run luna-corpus:test`
- `pnpm nx run luna-corpus:lint`
- `pnpm nx show project luna-corpus --json`
- 环境可用时运行 `pnpm nx run luna-corpus:db-migrate`

## 验收标准

- `luna-corpus` 有 tenant/workspace/knowledge base 模型和 P0-M2 migration。
- documents 和 conversations 都归属到 knowledge base。
- 需要知识库隔离的 API 都要求 header 上下文。
- 跨 knowledge base 的 document/conversation 访问返回 `404`。
- Chroma metadata 和 query filter 都包含 `knowledge_base_id`。
- QA 检索不会回退到全局结果。
- P0-M2 不包含用户、membership、RBAC 或认证逻辑。

## 实施顺序

1. 添加模型测试并扩展 SQLAlchemy models。
2. 添加 P0-M2 Alembic migration 和 migration 结构测试。
3. 添加 request context dependency 和上下文测试。
4. 添加 tenant/workspace/knowledge base 最小 API。
5. 修改文档 API，使其按当前 knowledge base 写入和过滤。
6. 修改 DocumentProcessor 和 vectorstore metadata/filter。
7. 修改 QA graph/service 路径以传递 `knowledge_base_id`。
8. 修改 conversation/memory 路径以绑定并校验 knowledge base。
9. 更新 README 或相关文档说明 header 上下文。
10. 运行完整测试、lint 和 Nx target 验证。
