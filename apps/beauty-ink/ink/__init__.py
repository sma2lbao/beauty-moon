"""beauty-ink：本地优先的个人知识库（RAG 问答）应用。

技术栈：
- LlamaIndex（检索增强生成框架）
- DeepSeek（LLM，OpenAI 兼容接口）
- BAAI/bge-m3（本地 Embedding，首次运行下载约 2GB）
- ChromaDB（向量持久化，存储于 ./data/chroma）
"""

__version__ = "0.1.0"
