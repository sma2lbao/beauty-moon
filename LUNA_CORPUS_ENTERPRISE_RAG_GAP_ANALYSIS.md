# Luna Corpus 企业级 RAG 落地差距分析

## 结论摘要

`apps/luna-corpus` 当前已经具备 RAG 原型的核心闭环：文档创建、切分、向量化、Chroma 检索、LLM 生成、SSE 流式问答、多轮会话记忆，以及 Agent 工具接入。距离企业级 RAG 落地，主要差距不在“能否回答问题”，而在知识治理、安全权限、异步吞吐、检索质量、评测闭环、可观测性、运维部署和合规审计这些生产级模块。

建议按三阶段推进：

1. **P0：可上线底座** — 补齐认证授权、租户/知识库隔离、异步索引任务、文件摄取、数据库迁移、基础观测、生产配置。
2. **P1：可规模化运营** — 补齐混合检索、重排、元数据过滤、质量评测、反馈闭环、版本治理、增量同步。
3. **P2：企业增强能力** — 补齐高级权限、水印/脱敏、知识图谱、成本治理、多模型路由、A/B 实验和管理后台。

## 当前已有能力

| 能力 | 当前状态 | 代码证据 |
| --- | --- | --- |
| FastAPI 服务入口 | 已有 API 服务和路由挂载 | `apps/luna-corpus/app/main.py:24` 定义应用，`apps/luna-corpus/app/main.py:41` 挂载 QA 路由 |
| 文档 CRUD | 已有纯文本文档创建、列表、查询、删除 | `apps/luna-corpus/app/api/routes.py:234` 创建文档，`apps/luna-corpus/app/api/routes.py:272` 列表，`apps/luna-corpus/app/api/routes.py:343` 删除 |
| 文档切分与向量化 | 已有同步切分、embedding、写入向量库 | `apps/luna-corpus/app/services/document_processor.py:13` 定义处理器，`apps/luna-corpus/app/services/document_processor.py:77` 处理文档 |
| 向量库 | 使用本地持久化 Chroma | `apps/luna-corpus/app/db/vectorstore.py:24` 创建 Chroma client，`apps/luna-corpus/app/db/vectorstore.py:37` 创建 collection |
| 基础向量检索 | 支持 top_k 向量相似度查询 | `apps/luna-corpus/app/db/vectorstore.py:73` 检索函数，`apps/luna-corpus/app/graph/rag_graph.py:61` 检索节点 |
| RAG 生成 | 使用 LangGraph 串起 memory、retrieve、generate | `apps/luna-corpus/app/graph/rag_graph.py:162` 创建 RAG graph，`apps/luna-corpus/app/graph/rag_graph.py:198` 问答入口 |
| 流式输出 | 支持 SSE 流式问答 | `apps/luna-corpus/app/api/routes.py:212` 流式 QA API，`apps/luna-corpus/app/graph/rag_graph.py:227` 流式生成 |
| 多轮会话 | 有 conversation/message 表和多轮 API | `apps/luna-corpus/app/db/models.py:106` 会话模型，`apps/luna-corpus/app/api/routes.py:590` 多轮问答 |
| 多模型配置 | 支持 Ollama、Ark、Doubao embedding 配置 | `apps/luna-corpus/app/core/config.py:10` provider 枚举，`apps/luna-corpus/app/services/llm.py:98` chat model factory |
| Agent 工具接入 | RAG search 可作为 Agent tool 使用 | `apps/luna-corpus/app/agent/tools/rag_search.py:1` RAG search tool，`apps/luna-corpus/app/api/agent_routes.py:70` 注册工具 |
| 测试基础 | 有服务、图、DB、Agent 相关测试 | `apps/luna-corpus/tests/graph/test_rag_graph.py`，`apps/luna-corpus/tests/db/test_vectorstore.py`，`apps/luna-corpus/tests/agent/test_integration.py` |

## P0：企业上线前必须补齐的模块

| 模块 | 缺口 | 为什么是 P0 | 当前证据 | 建议落地方式 |
| --- | --- | --- | --- | --- |
| 身份认证与 API 授权 | 所有文档、会话、问答接口当前没有认证依赖，CORS 允许任意来源 | 企业知识库通常包含内部资料，未授权访问会直接阻断上线 | `apps/luna-corpus/app/main.py:32` CORS `allow_origins=["*"]`；`apps/luna-corpus/app/api/routes.py:166`、`apps/luna-corpus/app/api/routes.py:234` 等核心接口无用户依赖 | 引入 OAuth/OIDC/JWT 中间件；所有写入、检索、问答接口绑定 `current_user`；关闭生产环境 wildcard CORS |
| 租户、空间、知识库隔离 | Document、Chunk、Conversation 没有 tenant_id、workspace_id、knowledge_base_id | 企业 RAG 必须按组织、部门、项目隔离知识和会话 | `apps/luna-corpus/app/db/models.py:52` Document 只有 title/source/content/status；`apps/luna-corpus/app/db/models.py:81` Chunk 只有 document_id/content | 增加 Tenant/Workspace/KnowledgeBase 模型；文档、chunk、conversation、向量 metadata 全部带隔离键；检索强制 filter |
| 权限模型与 ACL | 没有文档级、知识库级、会话级权限 | 仅有认证不足以控制谁能读哪些知识 | 代码搜索未见 `permission`、`rbac`、`role` 相关业务模型；`apps/luna-corpus/app/db/models.py` 只有文档、chunk、会话、消息 | 先实现 RBAC：owner/admin/member/viewer；再补文档 ACL 或部门同步；检索前和生成 sources 前都做权限过滤 |
| 文件摄取与解析管线 | 当前只支持 API 传入 title/content，没有 PDF、Office、HTML、图片 OCR、网页、对象存储导入 | 企业知识源通常来自文件库、网页、工单、Confluence、飞书/钉钉等，纯文本录入不可运营 | `apps/luna-corpus/app/api/routes.py:59` DocumentCreate 只有 title/content/source；依赖中未见 unstructured、pypdf、docx、OCR 组件 | 建立 ingestion 模块：上传、解析、清洗、结构化抽取、失败重试；先支持 PDF/DOCX/Markdown/HTML，再扩展连接器 |
| 异步索引任务 | 文档处理在请求内同步执行，embedding 和写向量库会阻塞 API | 大文档、批量导入、云 embedding 都会超时；生产需要任务状态和重试 | `apps/luna-corpus/app/api/routes.py:362` `/process` 直接调用 `processor.process_document`；`apps/luna-corpus/app/services/document_processor.py:118` 同步生成 embeddings | 引入队列和 worker，例如 Redis/Celery、RQ 或 Dramatiq；Document 增加 job_id、error_message、processed_at；API 返回任务状态 |
| 数据库迁移 | 启动时 `create_all`，缺少 Alembic 等迁移体系 | 企业上线后 schema 变更不能依赖自动建表，必须可审计、可回滚 | `apps/luna-corpus/app/db/database.py:29` `Base.metadata.create_all`；`apps/luna-corpus/scripts/create_tables.py:18` 手动 create/drop | 引入 Alembic；禁止生产自动 create_all；迁移脚本纳入 CI |
| 生产级向量库部署 | 使用本地 Chroma 持久化目录，缺少 HA、备份、容量规划和集合隔离 | 本地文件型向量库难以满足多实例、高可用、备份恢复和权限隔离 | `apps/luna-corpus/app/core/config.py:39` `CHROMA_DATA_DIR`；`apps/luna-corpus/app/db/vectorstore.py:28` `PersistentClient` | 短期可部署独立 Chroma server；中期评估 pgvector、Milvus、Qdrant、Elasticsearch/OpenSearch hybrid；向量库 metadata 必须可过滤 |
| 基础可观测性 | 只有健康检查雏形，没有结构化日志、trace、metrics、请求 ID | RAG 问题排查必须知道检索结果、prompt、模型延迟、token、错误率 | 关键词搜索未见 metrics/trace/audit；`apps/luna-corpus/app/services/llm.py:250` 仅返回 provider 状态 | 增加 structured logging、OpenTelemetry、Prometheus metrics；记录 request_id、tenant_id、retrieval latency、LLM latency、token usage |
| 安全与输入防护 | 缺少速率限制、请求大小限制、Prompt Injection 防护、敏感信息处理 | 企业 RAG 容易面对数据外泄、提示注入、滥用和成本攻击 | `apps/luna-corpus/app/api/routes.py:38` 问题长度限制较基础；未见 rate limit、guardrail、PII 过滤 | 增加 API rate limit、上传大小限制、内容安全扫描、prompt injection 检测、输出引用约束和敏感信息脱敏 |
| 部署与运行手册 | README 仍是占位描述，缺少环境、依赖、启动、生产部署说明 | 企业交付需要可复现部署、依赖服务说明和故障处理 | `apps/luna-corpus/README.md:1` 只有标题和占位描述；`.env.example` 只有基础配置 | 补 README、Dockerfile/Compose、环境变量说明、服务依赖、健康检查、备份恢复、升级步骤 |

## P1：规模化运营需要补齐的模块

| 模块 | 缺口 | 价值 | 当前证据 | 建议落地方式 |
| --- | --- | --- | --- | --- |
| 混合检索 | 只有向量检索，没有关键词/BM25/结构化过滤融合 | 企业文档中编号、术语、人名、代码、表格常需要 lexical search | `apps/luna-corpus/app/db/vectorstore.py:91` 只调用 Chroma `query`；未见 Elasticsearch/OpenSearch/BM25 | 引入 BM25 或 OpenSearch；实现 hybrid retriever，支持权重融合和 metadata filter |
| 重排 rerank | 检索结果直接进入 prompt，没有 cross-encoder 或 LLM rerank | top_k 向量结果噪声会显著影响回答质量 | `apps/luna-corpus/app/graph/rag_graph.py:76` 检索后直接格式化；`apps/luna-corpus/app/graph/rag_graph.py:129` 直接拼 context | 增加 rerank service；优先支持本地 bge-reranker 或云 rerank；记录 rerank 前后分数 |
| 元数据和分面过滤 | Chunk metadata 基本为空，向量 metadata 仅 document_id/chunk_id | 无法按知识库、部门、时间、文档类型、版本过滤 | `apps/luna-corpus/app/services/document_processor.py:71` `chunk_metadata=None`；`apps/luna-corpus/app/db/vectorstore.py:60` metadata 只有 ids | 定义 metadata schema；解析阶段写入 source_type、author、created_at、version、section、access_scope |
| 文档版本与增量同步 | 文档只有 updated_at，没有版本、hash、来源同步状态 | 企业知识会频繁更新，需要避免重复索引和旧版本污染 | `apps/luna-corpus/app/db/models.py:52` Document 无 version/hash/source connector 字段 | 增加 content_hash、version、external_id、sync_cursor；支持增量更新、回滚、过期 chunk 清理 |
| 知识质量评测 | 缺少 RAG eval 数据集、离线评测、回归门禁 | 没有指标就无法判断改 chunk、embedding、prompt 后是否变好 | 测试以单元/集成为主，未见 eval dataset 或 retrieval/generation 指标 | 建立 golden QA 集；评估 recall@k、MRR、faithfulness、answer correctness、citation accuracy；接入 CI 或定期任务 |
| 用户反馈闭环 | 问答接口没有 thumbs up/down、纠错、人工标注 | 企业落地后需要靠反馈持续优化知识和检索 | `apps/luna-corpus/app/api/routes.py:51` AnswerResponse 只有 answer/sources/time；无 feedback 模型 | 增加 answer_id、feedback 表、错误类型、人工标注入口；反馈进入评测集和知识修复队列 |
| 引用与可解释性增强 | Source 只有 document_id、chunk 摘要、分数，缺少标题、页码、段落、链接 | 企业用户需要定位原文以建立信任 | `apps/luna-corpus/app/api/routes.py:42` SourceResponse 支持 document_title 但未填充；`apps/luna-corpus/app/graph/rag_graph.py:147` sources 只有 document_id/chunk_content/score | chunk metadata 增加 page、heading、offset、source_url；生成答案要求逐句或段落引用 |
| Prompt 与模板治理 | Prompt 构建集中但缺少版本、实验、灰度 | prompt 改动会影响线上质量，需要可回滚和对比 | `apps/luna-corpus/app/services/prompt_builder.py` 存在，但配置未见 prompt version 或实验管理 | Prompt 模板版本化；记录每次请求使用的 prompt_version；支持灰度和回滚 |
| 成本与配额统计 | 未记录 token、模型调用次数、embedding 批量成本 | 云模型场景必须控成本、防滥用、做部门分摊 | `apps/luna-corpus/app/services/llm.py:161` 直接生成响应，未记录 token usage | 增加 model_usage 表；记录 prompt_tokens、completion_tokens、embedding_tokens、provider、cost_estimate |

## P2：企业增强和长期竞争力模块

| 模块 | 缺口 | 适用时机 | 建议 |
| --- | --- | --- | --- |
| 管理后台 | 当前只有 API，没有知识库运营界面 | 多团队使用、非研发上传和治理知识时 | 建知识库管理、任务监控、反馈审核、权限配置、评测看板 |
| 高级数据治理 | 缺少数据分级、保留策略、删除证明、审计报表 | 涉及合规、法务、内控时 | 增加分类分级、保留期限、删除审计、导出审计 |
| 多模型路由 | provider 选择是全局配置，不支持按任务动态路由 | 多模型成本/质量优化阶段 | 按租户、知识库、问题类型、上下文长度路由模型和 embedding |
| 知识图谱/结构化检索 | 没有实体关系抽取和图谱查询 | 复杂业务规则、产品/组织/制度关系密集时 | 从实体抽取、关系索引、GraphRAG 子流程逐步引入 |
| A/B 实验平台 | 缺少检索、rerank、prompt、模型实验能力 | 系统进入持续优化阶段 | 对 retriever、reranker、prompt、model 做实验分流和指标对比 |
| 灾备与多区域 | 缺少备份恢复、向量索引重建、跨区域部署策略 | SLA 要求明确后 | 定义 RPO/RTO；定期备份 MySQL、对象存储、向量库；提供一键重建索引 |

## 推荐落地顺序

### 阶段 1：上线安全底座

1. 认证授权与 CORS 收敛。
2. Tenant/Workspace/KnowledgeBase 数据模型和检索隔离。
3. RBAC/ACL 最小权限模型。
4. Alembic 数据库迁移。
5. Docker/Compose 或 Kubernetes 部署说明。

阶段目标：任何 API 请求都能回答“谁在访问、访问哪个知识库、是否有权限”。

### 阶段 2：可运营知识摄取

1. 文件上传与解析：PDF、DOCX、Markdown、HTML。
2. 异步索引任务和失败重试。
3. 文档版本、hash、增量同步。
4. 任务状态、错误原因、重建索引能力。

阶段目标：知识进入系统不再依赖手工粘贴文本，且大文档和批量任务不会阻塞 API。

### 阶段 3：检索质量提升

1. Metadata schema 和强制过滤。
2. Hybrid search。
3. Rerank。
4. 更完整的 source citation，包括标题、页码、段落、链接。
5. Prompt 版本化。

阶段目标：回答质量和可解释性可稳定提升，且能定位原文。

### 阶段 4：评测、反馈和观测闭环

1. RAG golden QA 数据集。
2. 离线评测和回归指标。
3. 用户反馈模型和 API。
4. OpenTelemetry、Prometheus、结构化日志。
5. Token/cost usage 统计。

阶段目标：每次改动都能用指标评估，线上问题能被定位和复盘。

## 关键风险

1. **安全风险最高**：当前 API 缺认证、权限和租户隔离，不适合直接接入真实企业知识。
2. **索引链路会成为瓶颈**：同步 embedding 和本地 Chroma 适合开发验证，不适合批量文档和多实例部署。
3. **质量不可度量**：没有评测集和反馈表，检索或 prompt 改动只能靠人工感觉判断。
4. **知识源覆盖不足**：只支持纯文本 content，不足以支撑企业真实文件和系统连接器。
5. **运维不可观测**：缺少 trace、metrics、结构化日志后，线上回答慢、错、幻觉、无引用都难定位。

## 建议的最小企业可用版本范围

如果目标是尽快落地一个“企业内部试点可用”的版本，建议至少包含：

- 登录认证和知识库级权限。
- 单租户或最小多租户隔离。
- PDF/DOCX/Markdown 上传解析。
- 异步索引任务和状态查询。
- Chroma server 或可运维的向量数据库部署方案。
- Metadata filter、基础 hybrid search 或 rerank 二选一。
- 回答引用包含文档标题和原文定位。
- 基础日志、指标和请求追踪。
- 10-30 条 golden QA 评测集。
- 部署文档和环境变量说明。

完成上述范围后，`luna-corpus` 才更接近企业级 RAG 的 MVP，而不是仅可演示的 RAG 原型。
