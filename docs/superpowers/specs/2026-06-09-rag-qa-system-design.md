# 知识库问答系统 (RAG Q&A System) 设计文档

**日期**: 2026-06-09
**状态**: 已批准

---

## 1. 项目概述

**项目名称**: 知识库问答系统
**项目类型**: RAG (检索增强生成) 问答应用
**核心功能**: 基于 MySQL 存储的文档数据，通过向量检索和本地 LLM 生成答案
**目标用户**: 需要从文档资料库中快速获取答案的用户

---

## 2. 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| 前端 | Next.js | 用户界面 |
| 后端 API | FastAPI (Python) | 业务逻辑和 RAG 流程 |
| 主数据库 | MySQL | 存储文档、配置等结构化数据 |
| 向量数据库 | Chroma | 存储文档向量嵌入，支持相似度检索 |
| LLM | Ollama (Llama 3.1) | 本地大语言模型推理 |
| Embeddings | Ollama (nomic-embed-text) | 文本向量化 |
| RAG 框架 | LangChain (Python) | LangChain + LangGraph 实现 RAG 流程 |

---

## 3. 系统架构

```
┌─────────────┐          ┌──────────────┐
│  Web UI     │          │  API Server  │
│  (Next.js)  │◄────────►│  (FastAPI)   │
└─────────────┘  REST    └──────┬───────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
      ┌───▼───┐           ┌────▼────┐        ┌─────▼─────┐
      │ MySQL │           │ Chroma  │        │  Ollama   │
      │(主数据)│           │(向量存储)│        │(本地模型) │
      └───────┘           └─────────┘        └───────────┘
```

**架构决策**:
- Web UI 和 API Server 分离部署，利于独立扩展
- MySQL + Chroma 双数据库：MySQL 负责结构化数据和事务，Chroma 负责向量检索
- Ollama 本地运行，无需云端 API 费用

---

## 4. 数据模型

### 4.1 documents 表 (文档)

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | CHAR(36) | PRIMARY KEY | UUID |
| title | VARCHAR(500) | NOT NULL | 文档标题 |
| source | VARCHAR(1000) | | 来源 URL/文件路径 |
| content | LONGTEXT | NOT NULL | 完整文档内容 |
| has_tables | BOOLEAN | DEFAULT FALSE | 是否含表格 |
| has_code | BOOLEAN | DEFAULT FALSE | 是否含代码 |
| status | ENUM | DEFAULT 'pending' | pending/processing/completed/error |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

### 4.2 chunks 表 (文档片段)

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | CHAR(36) | PRIMARY KEY | UUID |
| document_id | CHAR(36) | FOREIGN KEY | 关联文档 ID |
| content | TEXT | NOT NULL | 片段文本内容 |
| content_type | ENUM | DEFAULT 'text' | text/table/code |
| metadata | JSON | | 额外信息 |
| chunk_index | INT | NOT NULL | 片段序号 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |

**metadata 字段结构**:
```json
{
  "code_language": "python",
  "table_format": "markdown"
}
```

### 4.3 Chroma Collection

**集合名称**: `document_chunks`

**文档结构**:
```json
{
  "id": "chunk-uuid",
  "embedding": [0.1, 0.2, ...],
  "document": "chunk text content",
  "metadata": {
    "document_id": "doc-uuid",
    "chunk_id": "chunk-uuid",
    "content_type": "text"
  }
}
```

---

## 5. API 设计

### 5.1 问答接口

**POST /api/v1/qa/query**

请求:
```json
{
  "question": "如何配置系统？",
  "top_k": 5
}
```

响应:
```json
{
  "answer": "根据文档，配置步骤如下...",
  "sources": [
    {
      "document_id": "uuid",
      "document_title": "配置指南",
      "chunk_content": "第一步，打开配置文件...",
      "relevance_score": 0.95
    }
  ],
  "processing_time_ms": 1234
}
```

### 5.2 文档管理接口

**POST /api/v1/documents**
- 创建文档记录
- 请求体: `{ "title": "...", "content": "...", "source": "..." }`

**GET /api/v1/documents**
- 列出所有文档
- 支持分页和状态筛选

**GET /api/v1/documents/{id}**
- 获取文档详情

**DELETE /api/v1/documents/{id}**
- 删除文档（同时删除关联 chunks 和 Chroma 向量）

**POST /api/v1/documents/{id}/process**
- 触发文档处理流程（分块 → 向量化 → 存入 Chroma）

### 5.3 健康检查

**GET /api/v1/health**
```json
{
  "status": "ok",
  "mysql": "connected",
  "chroma": "connected",
  "ollama": "connected"
}
```

---

## 6. RAG 流程 (基于 LangChain + LangGraph)

### 6.1 技术选型理由

- **LangChain**: 提供标准化的 RAG 组件（Document Loader、Text Splitter、VectorStore、Chain）
- **LangGraph**: 使用有向图编排复杂 RAG 流程，支持条件分支、状态管理
- **LangChain Ollama 集成**: 原生支持 Ollama 模型和 embeddings

### 6.2 文档处理流程 (LangChain)

```
1. 接收原始文档 (MySQL documents 表)
         │
         ▼
2. Document Loader + 内容预处理
   - 使用 LangChain Document 标准化
   - 检测内容类型 (text/table/code)
         │
         ▼
3. Text Splitter 智能分块
   - RecursiveCharacterTextSplitter
   - 保留代码块和表格完整
   - 目标块大小: 500-1000 字符
         │
         ▼
4. 向量化 + 存储
   - OllamaEmbeddings 生成向量
   - Chroma.from_documents 存储
         │
         ▼
5. 更新状态
   - documents.status = 'completed'
   - 关联 chunks 已生成
```

### 6.3 问答流程 (LangGraph)

```
用户输入问题
         │
         ▼
┌─────────────────────┐
│   retrieve_node     │  ← LangGraph Node
│ - 问题向量化          │
│ - Chroma 相似度检索  │
│ - 返回相关 chunks    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  grade_node (可选)   │  ← 过滤低质量检索结果
│ - 判断相关性阈值     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  generate_node      │  ← LangGraph Node
│ - 构建 RAG prompt   │
│ - Ollama 生成答案   │
└──────────┬──────────┘
           │
           ▼
返回结果 (答案 + 来源)
```

**LangGraph 状态定义**:
```python
class RAGState(TypedDict):
    question: str
    retrieved_docs: List[Document]
    answer: str
    sources: List[dict]
```

---

## 7. 前端页面

### 7.1 页面结构

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | 首页 | 搜索入口，快速提问 |
| `/ask` | 问答页 | 提问并查看答案和来源 |
| `/documents` | 文档列表 | 管理所有文档 |
| `/documents/[id]` | 文档详情 | 查看单个文档内容和状态 |
| `/settings` | 设置页 | 系统配置 |

### 7.2 问答页面交互

1. 用户在输入框输入问题
2. 点击"提问"按钮
3. 显示 loading 状态（带进度指示）
4. 返回答案后展示：
   - AI 回答内容
   - 引用来源列表（可折叠展开）
5. 点击来源可跳转至对应文档详情
6. 支持复制答案

---

## 8. 配置项

| 配置项 | 环境变量 | 默认值 |
|--------|----------|--------|
| MySQL 连接 | `DATABASE_URL` | `mysql://user:pass@localhost:3306/rag_db` |
| Chroma 数据目录 | `CHROMA_DATA_DIR` | `./data/chroma` |
| Ollama 地址 | `OLLAMA_BASE_URL` | `http://localhost:11434` |
| LLM 模型 | `OLLAMA_MODEL` | `llama3.1` |
| Embeddings 模型 | `OLLAMA_EMBED_MODEL` | `nomic-embed-text` |
| 向量检索数量 | `RETRIEVAL_TOP_K` | `5` |

---

## 9. 项目结构

```
beautymoon/
├── apps/
│   └── luna-corpus/            # FastAPI 后端 (LangChain + LangGraph)
│       ├── app/
│       │   ├── api/            # API 路由
│       │   ├── core/           # 核心配置
│       │   ├── models/         # 数据模型
│       │   ├── services/       # 业务逻辑 (RAG chains)
│       │   ├── graph/          # LangGraph 流程编排
│       │   └── db/             # 数据库连接 (MySQL + Chroma)
│       ├── tests/
│       └── pyproject.toml
│
├── packages/
│   └── ui/                     # Next.js 前端 (待创建)
│       ├── app/
│       │   ├── page.tsx       # 首页
│       │   ├── ask/page.tsx    # 问答页
│       │   ├── documents/      # 文档管理
│       │   └── settings/       # 设置页
│       └── ...
│
└── docs/
    └── superpowers/
        └── specs/              # 设计文档
```

---

## 10. 优先实现顺序

1. **Phase 1: 基础后端**
   - FastAPI 项目结构
   - MySQL 连接和模型
   - Chroma 集成
   - Ollama 集成

2. **Phase 2: RAG 核心**
   - 文档分块逻辑
   - 向量化流程
   - 问答流程

3. **Phase 3: API 层**
   - 文档 CRUD 接口
   - 问答查询接口
   - 健康检查

4. **Phase 4: 前端**
   - Next.js 项目初始化
   - 问答页面
   - 文档管理页面

---

## 11. 待后续决定

- [ ] 图片处理策略（后续版本）
- [ ] 用户认证机制
- [ ] 文档上传方式（API / Web）
