"""贯穿一次 agent 执行的运行上下文。"""
import time
from dataclasses import dataclass


@dataclass
class AgentRunContext:
    """一次 agent 执行的全链路上下文与可变累加器。"""

    run_id: str
    tenant_id: str
    workspace_id: str
    knowledge_base_id: str
    user_id: str
    conversation_id: str | None
    mode: str
    max_steps: int
    timeout_s: int
    max_recursion_depth: int
    start_time: float
    query: str = ""
    memory_history: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    steps_count: int = 0

    def elapsed_s(self) -> float:
        """从 start_time 起的墙钟耗时（秒）。"""
        return time.time() - self.start_time
