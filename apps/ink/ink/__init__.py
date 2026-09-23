"""ink：本地优先的个人知识库（RAG 问答）应用。

技术栈：
- LlamaIndex（检索增强生成框架）
- DeepSeek（LLM，OpenAI 兼容接口）
- BAAI/bge-m3（本地 Embedding，首次运行下载约 2GB）
- ChromaDB（向量持久化，存储于 ./data/chroma）
"""

# 必须在任何 huggingface_hub / llama_index 导入之前执行：
# 这些库在 import 时就把 HF_HOME / HF_ENDPOINT 读成模块级常量。
# 自动把仓库 .cache 指给它们，避免忘记 source .cache/sandbox-env.sh
# 时去连接 huggingface.co 而报 OSError（详见 _bootstrap 模块文档）。
from ._bootstrap import bootstrap_cache_env as _bootstrap_cache_env

_bootstrap_cache_env()

__version__ = "0.1.0"
