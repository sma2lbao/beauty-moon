"""Tests for Nx project configuration."""

import json
from pathlib import Path


def load_project_config() -> dict:
    project_root = Path(__file__).parents[1]
    return json.loads((project_root / "project.json").read_text())


def test_test_target_uses_workspace_dev_dependencies():
    config = load_project_config()
    target = config["targets"]["test"]

    assert target["options"]["cwd"] == "{projectRoot}"
    assert target["options"]["command"] == "uv run --project ../.. pytest tests/"
