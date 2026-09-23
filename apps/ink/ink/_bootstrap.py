"""缓存路径自动引导（包导入时执行）。

背景：本仓库把 uv / LlamaIndex / HuggingFace 的缓存统一收敛到 monorepo 根目录的
``.cache/``（见 ``.cache/sandbox-env.sh`` 与根 ``.gitignore``），以便在受限/沙箱
环境下工作，也不污染用户主目录。

但 HuggingFaceEmbedding 只认环境变量：缓存目录取自
``llama_index.core.utils.get_cache_dir()``（读 ``LLAMA_INDEX_CACHE_DIR``），
HF 侧则读 ``HF_HOME`` / ``HF_ENDPOINT``。因此忘记 ``source .cache/sandbox-env.sh``
时，程序会去空的 ``~/.cache/llama_index`` 找模型，找不到便尝试连接
``https://huggingface.co``（国内不可达），最终抛出：

    OSError: We couldn't connect to 'https://huggingface.co' to load the files,
    and couldn't find them in the cached files.

本模块在 ``ink`` 包导入时（早于 huggingface_hub / llama_index 读取这些常量）
把缺失的变量补齐，让 ``uv run ink search`` / ``scan`` 无需手动 source 即可工作。

原则：**只填空值，绝不覆盖**用户或 .env 显式设置的值。
"""

import os
from pathlib import Path

# apps/ink/ink/_bootstrap.py → 包目录 = apps/ink/ink
_PACKAGE_DIR: Path = Path(__file__).resolve().parent

# 与 .cache/sandbox-env.sh 保持一致的默认值
_DEFAULTS: dict[str, str] = {
    "LLAMA_INDEX_CACHE_DIR": "llama_index",
    "HF_HOME": "huggingface",
}
_HF_ENDPOINT: str = "https://hf-mirror.com"
_HF_HUB_DISABLE_XET: str = "1"


def find_cache_dir(start: Path | None = None) -> Path | None:
    """从包目录向上查找 monorepo 根下的 ``.cache/`` 目录。

    判定依据：该目录内存在 ``llama_index`` 子目录或 ``sandbox-env.sh``
    （两者都是本仓库的约定产物），避免误判到无关目录。

    Args:
        start: 查找起点，默认包目录。

    Returns:
        找到的 ``.cache`` 绝对路径；未找到返回 None。
    """
    current = (start or _PACKAGE_DIR).resolve()
    for candidate in (current, *current.parents):
        cache = candidate / ".cache"
        if (cache / "llama_index").is_dir() or (cache / "sandbox-env.sh").is_file():
            return cache
    return None


def bootstrap_cache_env(start: Path | None = None) -> dict[str, str]:
    """补齐缓存相关环境变量，返回本次实际写入的键值对。

    仅当变量未设置或为空字符串时才写入；用户显式导出的值一律保留。

    Args:
        start: 查找 ``.cache`` 的起点，默认包目录（供测试注入）。

    Returns:
        本次实际设置的 ``{变量名: 值}``；未找到缓存目录时为空字典。
    """
    cache = find_cache_dir(start)
    if cache is None:
        return {}

    wanted: dict[str, str] = {
        **{key: str(cache / sub) for key, sub in _DEFAULTS.items()},
        "HF_ENDPOINT": _HF_ENDPOINT,
        "HF_HUB_DISABLE_XET": _HF_HUB_DISABLE_XET,
    }

    applied: dict[str, str] = {}
    for key, value in wanted.items():
        if not os.environ.get(key):
            os.environ[key] = value
            applied[key] = value
    return applied
