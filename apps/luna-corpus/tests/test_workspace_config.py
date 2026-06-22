"""Tests for workspace Python dependency configuration."""

import tomllib
from pathlib import Path


def load_workspace_pyproject() -> dict:
    workspace_root = Path(__file__).parents[3]
    return tomllib.loads((workspace_root / "pyproject.toml").read_text())


def test_workspace_dev_dependencies_include_async_pytest_plugin():
    config = load_workspace_pyproject()
    dev_dependencies = config["dependency-groups"]["dev"]

    assert "pytest-asyncio>=0.25.0" in dev_dependencies
