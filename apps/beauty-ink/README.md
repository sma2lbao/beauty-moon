# beauty-ink

本地优先的个人知识库（RAG 问答）应用：把本地文件夹中的笔记与文档建立索引，通过聊天界面提问，回答附带来源引用（文件名 + PDF 页码）。

## 技术栈

| 组件 | 选型 | 说明 |
| --- | --- | --- |
| 语言 / 环境 | Python 3.11+（锁定 3.12），uv | 虚拟环境与依赖管理 |
| RAG 框架 | LlamaIndex（`llama-index-core` 0.12+ 模块化拆分包） | 摄取 / 检索 / 问答编排 |
| LLM | `deepseek-chat`（DeepSeek，OpenAI 兼容接口） | 仅问答时调用云端 API |
| Embedding | `BAAI/bge-m3`（本地运行） | **首次运行自动下载约 2GB**，模型名可经 `.env` 更换 |
| 重排 | `BAAI/bge-reranker-v2-m3`（FlagEmbedding 本地运行） | **首次使用需下载约 2.3GB** |
| 向量库 | ChromaDB | 持久化到 `./data/chroma` |
| 文档解析 | MarkdownNodeParser / SentenceSplitter / PyMuPDF / python-docx | 四种格式 |
| UI | Streamlit | 聊天界面 + 流式输出 + 引用展示 |
| 配置 | pydantic-settings | 读取 `.env`，**API key 绝不进代码** |

## ⚠️ 首次运行会下载模型（重要）

本应用为本地优先设计，Embedding 与重排模型均在本地运行：

| 模型 | 体积 | 何时下载 |
| --- | --- | --- |
| `BAAI/bge-m3`（或你在 `.env` 配置的 EMBEDDING_MODEL） | **约 2GB** | 第一次 `ink scan` / 提问时 |
| `BAAI/bge-reranker-v2-m3` | **约 2.3GB** | 第一次 `query` / `search --hybrid` / UI 提问时 |

- 模型缓存在 `~/.cache/huggingface`（可用 `HF_HOME` 重定向），下载一次后离线可用
- 轻量替代：`EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5`（约 100MB）可用于快速体验
- **网络提示**：HuggingFace 主站在部分地区无法直连，可设置镜像 `HF_ENDPOINT=https://hf-mirror.com`；如遇 xet 下载器卡住，加 `HF_HUB_DISABLE_XET=1`
- 不想用重排：`.env` 中设置 `RERANKER_MODEL=`（留空）即跳过重排，仅用 RRF 融合

## 快速开始

```sh
cd apps/beauty-ink

# 1. 配置 .env（key 只放 .env，绝不进代码）
cp .env.example .env
# 编辑 .env：
#   DEEPSEEK_API_KEY  DeepSeek 平台的 key（问答用，https://platform.deepseek.com/）
#   EMBEDDING_MODEL   本地 Embedding 模型，如 BAAI/bge-m3（约 2GB）

# 2. 安装依赖（自动创建 .venv，锁定 Python 3.12）
uv sync

# 3. 摄取文档（首次会下载 Embedding 模型，见上方说明）
uv run python -m ink scan ./docs
# 等价命令：uv run ink scan ./docs / uv run ink ingest ./docs

# 4. 纯检索验证（不调用 LLM、无需 key）
uv run python -m ink search "烟酰胺入门浓度"

# 5. CLI 问答（需要 DEEPSEEK_API_KEY）
uv run python -m ink query "视黄醇孕期还能用吗"

# 6. 聊天 UI（Streamlit：流式输出 + 引用 + 过滤侧边栏）
uv run streamlit run ink/ui.py
# 或经 Nx：npx nx serve beauty-ink
```

## CLI 命令参考

| 命令 | 说明 |
| --- | --- |
| `ink scan <路径>`（别名 `ingest`） | 递归摄取 `.md/.txt/.pdf/.docx`，按文件 hash 增量更新：未入库→新增；未变化→跳过（输出"跳过 N 个未变化文件"）；变化→删旧节点再插入 |
| `ink search <问题> [--top-k N]` | 纯向量检索预览（不调 LLM、无需 key） |
| `ink search <问题> --hybrid` | 完整管线预览：向量 + BM25 → RRF 融合 → bge-reranker 重排 |
| `ink query <问题> [--top-k 10] [--top-n 5]` | 混合检索 + 重排 + DeepSeek 生成，末尾附引用列表 |

## 架构与数据流

**摄取管道（`ink scan`）**

```
递归扫描 ──► 计算文件 SHA-256 ──► 与库内 hash 对比 ─┬─ 未变化 → 跳过（零开销）
                                                    ├─ 新文件 → 读取解析
                                                    └─ 已变化 → 删除旧节点 → 读取解析
读取解析（readers.py）：
  .md/.txt  → 整体读取
  .pdf      → PyMuPDF 逐页提取（每页一个 Document，记录页码）
  .docx     → python-docx 段落拼接
metadata：source（绝对路径）/ file_name / file_hash / mtime（+PDF page/total_pages）
切分（scan.py）：
  .md      → MarkdownNodeParser（按标题结构切分）
  其余     → SentenceSplitter（chunk_size=512，overlap=64）
入库：HuggingFace Embedding 向量化 → ChromaDB 持久化（./data/chroma）
```

**检索管线（`ink query` / UI 提问）**

```
问题 ─► 向量检索（bge embedding，top 10）──┐
                                          ├→ RRF 融合去重 → bge-reranker-v2-m3 重排 → top 5
      └─► BM25 检索（中文字级切分，top 10）┘
top 5 → 拼装带编号上下文 → DeepSeek 流式生成（句末 [n] 标注）
回答末尾展示引用列表：[1] 护肤成分速查表.pdf（第 3 页）
```

- UI 侧：多轮对话保留**最近 5 轮**上下文；侧边栏可按文件类型 / 目录前缀过滤检索范围
- 性能：Embedding / Reranker / BM25 索引均为进程级缓存（UI 多轮复用，不重复加载 2GB 模型）

## 目录结构

```
beauty-ink/
├── ink/               # 主包（CLI / 配置 / 读取 / 摄取 / 检索 / 问答 / UI）
│   ├── cli.py         # 命令行入口（scan / search / query）
│   ├── config.py      # pydantic-settings（.env 驱动）
│   ├── readers.py     # 四格式读取（md/txt/pdf/docx → Document + metadata）
│   ├── scan.py        # 摄取编排（分格式切分 + hash 增量更新）
│   ├── store.py       # ChromaDB 封装（含增量维护）
│   ├── retrieval.py   # 混合检索（向量 + BM25 → RRF）+ bge-reranker 重排（进程级缓存）
│   ├── query.py       # 问答（拼装上下文 + DeepSeek + 引用溯源 Citation）
│   └── ui.py          # Streamlit 聊天 UI（流式 + 引用 + 过滤侧边栏 + 5 轮上下文）
├── docs/              # 测试文档（md / txt / pdf / docx 各若干）
├── data/chroma/       # ChromaDB 持久化目录（git 忽略）
├── .env.example       # 环境变量模板（复制为 .env 使用）
└── pyproject.toml     # uv 依赖清单（含 ink CLI 入口）
```

## 配置参考（.env）

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | ✅ | — | DeepSeek 平台 API key（仅问答需要） |
| `EMBEDDING_MODEL` | ✅ | — | 本地 Embedding 模型名，如 `BAAI/bge-m3` |
| `RERANKER_MODEL` | — | `BAAI/bge-reranker-v2-m3` | 重排模型；留空跳过重排 |
| `DEEPSEEK_BASE_URL` | — | `https://api.deepseek.com` | OpenAI 兼容接口地址 |
| `DEEPSEEK_MODEL` | — | `deepseek-chat` | 模型名 |
| `CHROMA_DIR` | — | `./data/chroma` | 向量库持久化目录 |
| `CHROMA_COLLECTION` | — | `beauty_ink` | collection 名称 |

## FAQ

**Q：换 Embedding 模型后报维度不匹配？**
ingest 与 query 必须使用同一模型。更换 `EMBEDDING_MODEL` 后删除 `data/chroma` 重新 `ink scan`。

**Q：改了文档再 scan 会重复入库吗？**
不会。按文件内容 hash 增量更新：未变化的文件跳过，变化的文件先删旧节点再插入。

**Q：API key 安全吗？**
key 只存于 `.env`（已被 `.gitignore` 忽略，含项目级与仓库级双重防护），代码与日志中不出现明文。

**Q：只想快速体验，不想下载 2GB 模型？**
`EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5`（约 100MB）+ `RERANKER_MODEL=`（跳过重排）。

## 里程碑

- [x] M1 项目骨架 + 依赖 + 最小示例（导入 3 个测试文档 → 检索命中）
- [x] M2 完整摄取管道（四种格式 + 增量更新 + metadata + PDF 页码）
- [x] M3 混合检索（向量 + BM25 / RRF 融合）+ bge-reranker-v2-m3 重排 + 引用溯源
- [x] M4 Streamlit 聊天 UI（流式输出 + 引用展示 + 过滤侧边栏 + 最近 5 轮上下文）
- [x] M5 README 完善
