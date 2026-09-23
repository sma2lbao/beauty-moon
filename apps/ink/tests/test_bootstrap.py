"""缓存路径自动引导（ink._bootstrap）的单元测试。

覆盖三点：缺失变量被补齐、显式设置不被覆盖、找不到 .cache 时保持无操作。
所有用例都基于 tmp_path 构造的假 monorepo，不依赖真实仓库缓存是否已下载。
"""

import os

from ink._bootstrap import bootstrap_cache_env, find_cache_dir

_KEYS = ("LLAMA_INDEX_CACHE_DIR", "HF_HOME", "HF_ENDPOINT", "HF_HUB_DISABLE_XET")


def _clear(monkeypatch) -> None:
    """清空所有被引导的变量，模拟"没有 source 环境脚本"的状态。"""
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def test_find_cache_dir_walks_up_to_monorepo_root(tmp_path):
    """从深层包目录向上应能找到含 .cache/llama_index 的仓库根。"""
    root = tmp_path / "repo"
    (root / ".cache" / "llama_index").mkdir(parents=True)
    start = root / "apps" / "ink" / "ink"
    start.mkdir(parents=True)

    assert find_cache_dir(start) == root / ".cache"


def test_bootstrap_fills_missing_vars(tmp_path, monkeypatch):
    """四个变量都缺失时，应全部指向仓库 .cache 并启用镜像。"""
    root = tmp_path / "repo"
    (root / ".cache" / "llama_index").mkdir(parents=True)
    start = root / "apps" / "ink" / "ink"
    start.mkdir(parents=True)
    _clear(monkeypatch)

    applied = bootstrap_cache_env(start=start)

    assert applied["LLAMA_INDEX_CACHE_DIR"] == str(root / ".cache" / "llama_index")
    assert applied["HF_HOME"] == str(root / ".cache" / "huggingface")
    assert os.environ["HF_ENDPOINT"] == "https://hf-mirror.com"
    assert os.environ["HF_HUB_DISABLE_XET"] == "1"


def test_bootstrap_keeps_explicit_values(tmp_path, monkeypatch):
    """用户显式导出的值必须保留，只补齐缺失项。"""
    root = tmp_path / "repo"
    (root / ".cache" / "sandbox-env.sh").parent.mkdir(parents=True)
    (root / ".cache" / "sandbox-env.sh").write_text("", encoding="utf-8")
    _clear(monkeypatch)
    monkeypatch.setenv("LLAMA_INDEX_CACHE_DIR", "/tmp/explicit")
    monkeypatch.setenv("HF_ENDPOINT", "https://example.invalid")

    applied = bootstrap_cache_env(start=root / "apps" / "ink")

    assert "LLAMA_INDEX_CACHE_DIR" not in applied
    assert "HF_ENDPOINT" not in applied
    assert os.environ["LLAMA_INDEX_CACHE_DIR"] == "/tmp/explicit"
    assert os.environ["HF_ENDPOINT"] == "https://example.invalid"
    # 未设置的仍被补齐
    assert applied["HF_HOME"] == str(root / ".cache" / "huggingface")


def test_bootstrap_noop_when_no_cache_dir(tmp_path, monkeypatch):
    """找不到 .cache 时不做任何设置（回退到默认行为）。"""
    _clear(monkeypatch)

    assert bootstrap_cache_env(start=tmp_path) == {}
    assert os.environ.get("LLAMA_INDEX_CACHE_DIR") is None
