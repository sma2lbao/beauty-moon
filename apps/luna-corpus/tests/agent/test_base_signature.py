"""base/factory 新签名冒烟测试。

覆盖 Task 8：
- AgentConfig 新增 timeout_s/max_recursion_depth 字段与默认值
- AgentFactory.create 透传 timeout_s/max_recursion_depth 到 config
- Agent.run 抽象签名前三个参数为 ctx/trace/db

注：第三条直接 inspect 抽象基类 Agent.run，避免耦合尚未在 Task 9
重写的具体模式子类（其 override 仍是旧签名 query）。
"""
import inspect

from app.agent.base import Agent, AgentConfig
from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.core.config import AgentMode


def test_config_has_timeout_and_recursion():
    """AgentConfig 默认应包含 timeout_s=120、max_recursion_depth=3。"""
    cfg = AgentConfig()
    assert cfg.timeout_s == 120
    assert cfg.max_recursion_depth == 3


def test_factory_threads_new_params():
    """AgentFactory.create 应将新参数写入 AgentConfig。"""
    agent = AgentFactory.create(
        AgentMode.REACT,
        tools=ToolRegistry(),
        max_steps=7,
        timeout_s=99,
        max_recursion_depth=2,
    )
    assert agent.config.max_steps == 7
    assert agent.config.timeout_s == 99
    assert agent.config.max_recursion_depth == 2


def test_run_signature_takes_ctx_trace_db():
    """Agent 抽象基类 run 的前三个形参应为 ctx/trace/db。"""
    params = list(inspect.signature(Agent.run).parameters)
    # 首位为 self
    assert params[0] == "self"
    assert params[1:4] == ["ctx", "trace", "db"]
