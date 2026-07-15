"""Agent 相关配置项的默认值测试。"""
from app.core.config import Settings


def test_agent_timeout_default():
    settings = Settings()
    assert settings.agent_timeout_s == 120


def test_agent_max_recursion_depth_default():
    settings = Settings()
    assert settings.agent_max_recursion_depth == 3
