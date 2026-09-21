"""应用配置模块。

通过 pydantic-settings 读取 .env / 环境变量；
所有 API key 只允许出现在 .env 中，绝不硬编码进代码。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（apps/beauty-ink/），用于定位 .env 与数据目录
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全局配置项。

    优先级：.env 文件 > 环境变量 > 代码默认值。
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        # .env 中可能出现本类未声明的键（如被注释掉默认值的项），忽略以免报错
        extra="ignore",
    )

    # ---- DeepSeek LLM ----
    # API key：只从 .env / 环境变量读取，代码与日志中绝不出现明文
    deepseek_api_key: str = ""
    # DeepSeek 走 OpenAI 兼容接口
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # ---- Embedding ----
    # 本地 Embedding 模型名：必须由使用者在 .env 中显式配置（EMBEDDING_MODEL）。
    # 示例：BAAI/bge-m3（约 2GB，效果最佳）/ BAAI/bge-small-zh-v1.5（约 100MB，轻量）。
    # 注意：ingest 与 query 必须使用同一模型；更换模型后需删除 data/chroma 重新入库。
    embedding_model: str = ""

    # ---- Reranker（重排）----
    # 混合检索后的重排模型（FlagEmbedding 加载，首次使用需下载约 2GB）。
    # 可在 .env 中用 RERANKER_MODEL 覆盖；留空则跳过重排（仅 RRF 融合取前 5）。
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # ---- ChromaDB 向量库 ----
    # 持久化目录：./data/chroma（已被 .gitignore 忽略）
    chroma_dir: Path = PROJECT_ROOT / "data" / "chroma"
    chroma_collection: str = "beauty_ink"

    # ---- 文本切分 ----
    chunk_size: int = 512
    chunk_overlap: int = 64


def get_settings() -> Settings:
    """获取配置单例（每次调用新建，供测试时覆盖环境变量）。"""
    return Settings()
