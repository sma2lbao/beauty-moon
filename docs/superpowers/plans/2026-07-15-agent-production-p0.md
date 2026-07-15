# Agent 生产化 P0（阻断级）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `apps/luna-corpus` 的 agent 从"能演示的原型"升级为"可上生产的可用 agent"：真正多步循环、原生 function-calling、接入治理设施（成本/配额/审计/记忆/租户隔离）、执行安全边界、可观测轨迹落库。

**Architecture:** 抽取共享"生产内核" `app/agent/core/`（context / trace / governance / llm_loop），4 个模式（direct/react/plan/langgraph）改为薄壳复用内核；新增 `agent_runs` + `agent_steps` 两张轨迹表；agent 路由改造为完整执行管线并新增回放 API。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2.0（`Mapped`/`mapped_column`）、Alembic、LangChain（`bind_tools` 原生 function-calling）、pytest。provider=ARK（`langchain_openai.ChatOpenAI`，OpenAI 兼容）与 Ollama。

## Global Constraints

- 包管理器统一 `npm`；测试用 `cd apps/luna-corpus && python -m pytest` 或 `npm exec nx test luna-corpus`。项目内已有 `.venv`。
- 迁移必须走 Alembic，禁止 `create_all`；新迁移 `down_revision = "20260714_0014"`（当前最新为 `20260714_0014_auth_login`）。
- 主键统一 `CHAR(36)` + `default=lambda: str(uuid.uuid4())`；隔离键列 `CHAR(36)`；时间列 `DateTime` + `server_default=func.now()`。
- 治理与可观测性是**旁路**：轨迹落库/成本计量失败一律 `fail-safe`（log warning + 不抛）；配额检查 `fail-open`（服务异常放行）。只有 LLM 本身失败才算 `failed`。
- 全部注释与文档用中文，与现有代码风格一致。
- 默认值（来自 spec）：`AGENT_TIMEOUT_S=120`、`agent_max_steps=10`（已存在）、`tool_result` 截断上限 **8192 字符**、递归深度上限 **3**。
- 单元/集成测试用 **mock LLM**，绝不打真实 provider，保证 CI 确定性。

---

## 文件结构

**新建：**
- `app/agent/core/__init__.py` — 内核包
- `app/agent/core/context.py` — `AgentRunContext` 数据类
- `app/agent/core/trace.py` — `TraceRecorder`（写 agent_runs/agent_steps，fail-safe）
- `app/agent/core/governance.py` — `HaltSignal` + `check_step`（每步预检）
- `app/agent/core/llm_loop.py` — `run_tool_loop`（原生 function-calling 循环引擎）
- `app/api/agent_runs_routes.py` — 回放 API（GET runs / GET runs/{id}）
- `alembic/versions/20260715_0015_agent_trace.py` — 两表迁移
- 测试：`tests/agent/core/test_trace.py`、`test_governance.py`、`test_llm_loop.py`；`tests/agent/test_run_pipeline.py`；`tests/api/test_agent_runs_routes.py`

**修改：**
- `app/core/config.py` — 新增 `agent_timeout_s`、`agent_max_recursion_depth`
- `app/db/models.py` — 新增 `AgentRun`、`AgentStep` 模型 + `AgentRunStatus`、`AgentStepType` 枚举
- `app/security/audit.py` — `AuditAction` 新增 `AGENT_QUERY = "agent.query"`
- `app/agent/base.py` — `Agent.run/run_stream` 接受 `AgentRunContext`
- `app/agent/factory.py` — `create` 透传 timeout/recursion
- `app/agent/modes/{direct,react,plan_execute,langgraph}.py` — 改为调用 `run_tool_loop`
- `app/api/agent_routes.py` — `/query` 和 `/stream` 改造为完整管线，响应加 `run_id`
- `app/main.py` — 挂载 `agent_runs_routes`

---

### Task 1: 配置项 — agent 超时与递归深度上限

**Files:**
- Modify: `apps/luna-corpus/app/core/config.py`（Agent 配置区块，约 257-269 行后追加）
- Test: `apps/luna-corpus/tests/core/test_config_agent.py`

**Interfaces:**
- Produces: `settings.agent_timeout_s: int`（默认 120）、`settings.agent_max_recursion_depth: int`（默认 3）

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/core/test_config_agent.py`：

```python
"""Agent 相关配置项的默认值测试。"""
from app.core.config import Settings


def test_agent_timeout_default():
    settings = Settings()
    assert settings.agent_timeout_s == 120


def test_agent_max_recursion_depth_default():
    settings = Settings()
    assert settings.agent_max_recursion_depth == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/core/test_config_agent.py -v`
Expected: FAIL（`AttributeError: 'Settings' object has no attribute 'agent_timeout_s'`）

- [ ] **Step 3: 追加配置字段**

在 `app/core/config.py` 的 `agent_plan_max_steps` 字段之后追加：

```python
    agent_timeout_s: int = Field(
        default=120, description="Agent 单次执行的墙钟超时（秒）"
    )
    agent_max_recursion_depth: int = Field(
        default=3, description="Agent 工具触发子调用时的最大嵌套深度"
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/core/test_config_agent.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/core/test_config_agent.py
git commit -m "feat(agent): 新增 agent 超时与递归深度配置"
```

---

### Task 2: 数据模型 — AgentRun / AgentStep

**Files:**
- Modify: `apps/luna-corpus/app/db/models.py`（在文件末尾 `QuotaCounter` 之后追加）
- Test: `apps/luna-corpus/tests/db/test_agent_trace_models.py`

**Interfaces:**
- Produces:
  - `AgentRunStatus`(str, enum)：`RUNNING="running"` `COMPLETED="completed"` `FAILED="failed"` `HALTED_QUOTA="halted_quota"` `HALTED_MAX_STEPS="halted_max_steps"` `HALTED_TIMEOUT="halted_timeout"`
  - `AgentStepType`(str, enum)：`REASONING="reasoning"` `TOOL_CALL="tool_call"` `TOOL_RESULT="tool_result"` `FINAL="final"`
  - `AgentRun` 模型，`__tablename__="agent_runs"`，字段见 Step 3
  - `AgentStep` 模型，`__tablename__="agent_steps"`，字段见 Step 3

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/db/test_agent_trace_models.py`：

```python
"""AgentRun / AgentStep 模型冒烟测试。"""
from app.db.models import AgentRun, AgentRunStatus, AgentStep, AgentStepType


def test_agent_run_defaults():
    run = AgentRun(
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="k1",
        user_id="u1",
        mode="react",
        query="hello",
    )
    assert run.id is not None
    assert run.status == AgentRunStatus.RUNNING
    assert run.steps_count == 0
    assert run.total_input_tokens == 0
    assert run.total_output_tokens == 0


def test_agent_step_defaults():
    step = AgentStep(
        run_id="r1",
        step_index=0,
        step_type=AgentStepType.REASONING,
    )
    assert step.id is not None
    assert step.step_index == 0
    assert step.step_type == AgentStepType.REASONING


def test_status_enum_values():
    assert AgentRunStatus.HALTED_QUOTA.value == "halted_quota"
    assert AgentRunStatus.HALTED_MAX_STEPS.value == "halted_max_steps"
    assert AgentRunStatus.HALTED_TIMEOUT.value == "halted_timeout"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/db/test_agent_trace_models.py -v`
Expected: FAIL（`ImportError: cannot import name 'AgentRun'`）

- [ ] **Step 3: 追加模型**

在 `app/db/models.py` 末尾（`QuotaCounter` 类之后）追加。所需符号 `uuid` `datetime` `Decimal` `CHAR` `String` `Text` `Integer` `Numeric` `Boolean` `DateTime` `JSON` `ForeignKey` `Enum` `func` `Mapped` `mapped_column` 均已在文件顶部导入：

```python
class AgentRunStatus(str, enum.Enum):
    """Agent 一次执行的终态。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    HALTED_QUOTA = "halted_quota"
    HALTED_MAX_STEPS = "halted_max_steps"
    HALTED_TIMEOUT = "halted_timeout"


class AgentStepType(str, enum.Enum):
    """Agent 单步类型。"""

    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL = "final"


class AgentRun(Base):
    """一次 agent 执行 = 一行；run 级聚合用量、成本、状态。"""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(CHAR(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(CHAR(36), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(CHAR(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(CHAR(36), nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus), default=AgentRunStatus.RUNNING, nullable=False
    )
    steps_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    steps: Mapped[list["AgentStep"]] = relationship(
        "AgentStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentStep.step_index",
    )


class AgentStep(Base):
    """一步 = 一行，属于某个 run。"""

    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[AgentStepType] = mapped_column(Enum(AgentStepType), nullable=False)
    thought: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_args: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="steps")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/db/test_agent_trace_models.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/tests/db/test_agent_trace_models.py
git commit -m "feat(agent): 新增 AgentRun/AgentStep 轨迹模型"
```

---

### Task 3: Alembic 迁移 — agent_runs / agent_steps 两表

**Files:**
- Create: `apps/luna-corpus/alembic/versions/20260715_0015_agent_trace.py`

**Interfaces:**
- Consumes: Task 2 的表结构定义
- Produces: 数据库中 `agent_runs`、`agent_steps` 两表

- [ ] **Step 1: 写迁移**

创建 `apps/luna-corpus/alembic/versions/20260715_0015_agent_trace.py`：

```python
"""agent trace: agent_runs, agent_steps

Revision ID: 20260715_0015
Revises: 20260714_0014
Create Date: 2026-07-15

"""
import sqlalchemy as sa
from alembic import op

revision = "20260715_0015"
down_revision = "20260714_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("workspace_id", sa.CHAR(36), nullable=False),
        sa.Column("knowledge_base_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("conversation_id", sa.CHAR(36), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("steps_count", sa.Integer(), nullable=False),
        sa.Column("total_input_tokens", sa.Integer(), nullable=False),
        sa.Column("total_output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])
    op.create_index("ix_agent_runs_workspace_id", "agent_runs", ["workspace_id"])
    op.create_index("ix_agent_runs_knowledge_base_id", "agent_runs", ["knowledge_base_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_index("ix_agent_runs_created_at", "agent_runs", ["created_at"])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("run_id", sa.CHAR(36), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=20), nullable=False),
        sa.Column("thought", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("tool_args", sa.JSON(), nullable=True),
        sa.Column("tool_result", sa.Text(), nullable=True),
        sa.Column("tool_success", sa.Boolean(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_steps_run_id", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("ix_agent_runs_created_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_knowledge_base_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_workspace_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_id", table_name="agent_runs")
    op.drop_table("agent_runs")
```

- [ ] **Step 2: 校验迁移链完整**

Run: `cd apps/luna-corpus && python -m alembic history | head -5`
Expected: 顶部出现 `20260714_0014 -> 20260715_0015 (head)`，无 "Multiple head" 报错。

- [ ] **Step 3: 提交**

```bash
git add apps/luna-corpus/alembic/versions/20260715_0015_agent_trace.py
git commit -m "feat(agent): agent_runs/agent_steps 迁移"
```

---

### Task 4: 内核 — AgentRunContext

**Files:**
- Create: `apps/luna-corpus/app/agent/core/__init__.py`（空文件）
- Create: `apps/luna-corpus/app/agent/core/context.py`
- Test: `apps/luna-corpus/tests/agent/core/__init__.py`（空文件）、`apps/luna-corpus/tests/agent/core/test_context.py`

**Interfaces:**
- Produces:
  - `AgentRunContext` 数据类，无默认值字段：`run_id: str`、`tenant_id: str`、`workspace_id: str`、`knowledge_base_id: str`、`user_id: str`、`conversation_id: str | None`、`mode: str`、`max_steps: int`、`timeout_s: int`、`max_recursion_depth: int`、`start_time: float`；有默认值字段：`query: str = ""`、`memory_history: str = ""`、可变累加器 `total_input_tokens: int = 0`、`total_output_tokens: int = 0`、`steps_count: int = 0`
  - `AgentRunContext.elapsed_s() -> float`（`time.time() - start_time`）
  - 注意：`query` 字段供各模式从 ctx 取用户输入（Task 9 使用 `ctx.query`）。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/agent/core/__init__.py`（空），再创建 `apps/luna-corpus/tests/agent/core/test_context.py`：

```python
"""AgentRunContext 测试。"""
from app.agent.core.context import AgentRunContext


def _make_ctx(**overrides):
    base = dict(
        run_id="r1",
        tenant_id="t1",
        workspace_id="w1",
        knowledge_base_id="k1",
        user_id="u1",
        conversation_id=None,
        mode="react",
        max_steps=10,
        timeout_s=120,
        max_recursion_depth=3,
        start_time=1000.0,
    )
    base.update(overrides)
    return AgentRunContext(**base)


def test_context_defaults():
    ctx = _make_ctx()
    assert ctx.memory_history == ""
    assert ctx.total_input_tokens == 0
    assert ctx.total_output_tokens == 0
    assert ctx.steps_count == 0


def test_elapsed_uses_start_time(monkeypatch):
    import app.agent.core.context as ctx_mod

    ctx = _make_ctx(start_time=1000.0)
    monkeypatch.setattr(ctx_mod.time, "time", lambda: 1002.5)
    assert ctx.elapsed_s() == 2.5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/core/test_context.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.agent.core'`）

- [ ] **Step 3: 实现**

创建 `apps/luna-corpus/app/agent/core/__init__.py`（空文件）。创建 `apps/luna-corpus/app/agent/core/context.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/core/test_context.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/agent/core/__init__.py apps/luna-corpus/app/agent/core/context.py apps/luna-corpus/tests/agent/core/
git commit -m "feat(agent): 新增 AgentRunContext 运行上下文"
```

---

### Task 5: 内核 — TraceRecorder（轨迹落库，fail-safe）

**Files:**
- Create: `apps/luna-corpus/app/agent/core/trace.py`
- Test: `apps/luna-corpus/tests/agent/core/test_trace.py`

**Interfaces:**
- Consumes: `AgentRun`、`AgentStep`、`AgentRunStatus`、`AgentStepType`（Task 2）；`AgentRunContext`（Task 4）
- Produces: `TraceRecorder` 类，构造 `TraceRecorder(db)`，方法：
  - `start_run(ctx: AgentRunContext, query: str) -> None`：插入 `agent_runs(status=RUNNING)`，主键取 `ctx.run_id`
  - `record_step(ctx, *, step_index, step_type, thought=None, tool_name=None, tool_args=None, tool_result=None, tool_success=None, input_tokens=None, output_tokens=None, latency_ms=0) -> None`：插入一行 `agent_steps`；`tool_result` 超 8192 字符截断并追加 `"...[truncated]"`
  - `end_run(ctx, *, status, final_answer, total_cost, latency_ms, error_message=None) -> None`：更新该 run 的终态字段与聚合
  - 所有方法 fail-safe：内部 try/except，失败 `logger.warning(...)` + `db.rollback()`，绝不抛
- 模块级常量 `TOOL_RESULT_MAX_CHARS = 8192`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/agent/core/test_trace.py`：

```python
"""TraceRecorder 落库与 fail-safe 测试。"""
import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.trace import TOOL_RESULT_MAX_CHARS, TraceRecorder
from app.db.models import AgentRun, AgentRunStatus, AgentStep, AgentStepType


def _ctx(run_id="r1"):
    return AgentRunContext(
        run_id=run_id, tenant_id="t1", workspace_id="w1", knowledge_base_id="k1",
        user_id="u1", conversation_id=None, mode="react", max_steps=10,
        timeout_s=120, max_recursion_depth=3, start_time=1000.0,
    )


def test_start_run_inserts_running_row(db_session):
    rec = TraceRecorder(db_session)
    ctx = _ctx()
    rec.start_run(ctx, query="hi")
    row = db_session.query(AgentRun).filter(AgentRun.id == "r1").first()
    assert row is not None
    assert row.status == AgentRunStatus.RUNNING
    assert row.query == "hi"


def test_record_step_persists(db_session):
    rec = TraceRecorder(db_session)
    ctx = _ctx()
    rec.start_run(ctx, query="hi")
    rec.record_step(ctx, step_index=0, step_type=AgentStepType.TOOL_CALL,
                    tool_name="rag_search", tool_args={"query": "x"}, latency_ms=5)
    steps = db_session.query(AgentStep).filter(AgentStep.run_id == "r1").all()
    assert len(steps) == 1
    assert steps[0].tool_name == "rag_search"
    assert steps[0].tool_args == {"query": "x"}


def test_record_step_truncates_tool_result(db_session):
    rec = TraceRecorder(db_session)
    ctx = _ctx()
    rec.start_run(ctx, query="hi")
    huge = "a" * (TOOL_RESULT_MAX_CHARS + 500)
    rec.record_step(ctx, step_index=0, step_type=AgentStepType.TOOL_RESULT,
                    tool_result=huge, tool_success=True)
    step = db_session.query(AgentStep).filter(AgentStep.run_id == "r1").first()
    assert len(step.tool_result) <= TOOL_RESULT_MAX_CHARS + len("...[truncated]")
    assert step.tool_result.endswith("...[truncated]")


def test_end_run_updates_status(db_session):
    rec = TraceRecorder(db_session)
    ctx = _ctx()
    rec.start_run(ctx, query="hi")
    rec.end_run(ctx, status=AgentRunStatus.COMPLETED, final_answer="done",
                total_cost=0, latency_ms=42)
    row = db_session.query(AgentRun).filter(AgentRun.id == "r1").first()
    assert row.status == AgentRunStatus.COMPLETED
    assert row.final_answer == "done"
    assert row.latency_ms == 42
    assert row.finished_at is not None


def test_record_step_failsafe_swallows(db_session):
    """db 抛错时 record_step 不得向上抛。"""
    class Boom:
        def add(self, *a, **k):
            raise RuntimeError("boom")
        def rollback(self):
            pass
    rec = TraceRecorder(Boom())
    ctx = _ctx()
    # 不抛即通过
    rec.record_step(ctx, step_index=0, step_type=AgentStepType.REASONING, thought="x")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/core/test_trace.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.agent.core.trace'`）

- [ ] **Step 3: 实现**

创建 `apps/luna-corpus/app/agent/core/trace.py`：

```python
"""Agent 轨迹记录器：写 agent_runs / agent_steps，全程 fail-safe。"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.agent.core.context import AgentRunContext
from app.db.models import AgentRun, AgentRunStatus, AgentStep, AgentStepType
from app.observability.logging import get_logger

logger = get_logger("luna.agent.trace")

TOOL_RESULT_MAX_CHARS = 8192


class TraceRecorder:
    """把 agent 执行轨迹落库；任何写库异常都 fail-safe（log + rollback + 不抛）。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def start_run(self, ctx: AgentRunContext, query: str) -> None:
        try:
            self.db.add(
                AgentRun(
                    id=ctx.run_id,
                    tenant_id=ctx.tenant_id,
                    workspace_id=ctx.workspace_id,
                    knowledge_base_id=ctx.knowledge_base_id,
                    user_id=ctx.user_id,
                    conversation_id=ctx.conversation_id,
                    mode=ctx.mode,
                    query=query,
                    status=AgentRunStatus.RUNNING,
                )
            )
            self.db.commit()
        except Exception:
            logger.warning("agent_trace_start_run_failed", exc_info=True)
            self._safe_rollback()

    def record_step(
        self,
        ctx: AgentRunContext,
        *,
        step_index: int,
        step_type: AgentStepType,
        thought: str | None = None,
        tool_name: str | None = None,
        tool_args: dict | None = None,
        tool_result: str | None = None,
        tool_success: bool | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int = 0,
    ) -> None:
        try:
            if tool_result is not None and len(tool_result) > TOOL_RESULT_MAX_CHARS:
                tool_result = tool_result[:TOOL_RESULT_MAX_CHARS] + "...[truncated]"
            self.db.add(
                AgentStep(
                    run_id=ctx.run_id,
                    step_index=step_index,
                    step_type=step_type,
                    thought=thought,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_result,
                    tool_success=tool_success,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                )
            )
            self.db.commit()
        except Exception:
            logger.warning("agent_trace_record_step_failed", exc_info=True)
            self._safe_rollback()

    def end_run(
        self,
        ctx: AgentRunContext,
        *,
        status: AgentRunStatus,
        final_answer: str | None,
        total_cost: Decimal | int,
        latency_ms: int,
        error_message: str | None = None,
    ) -> None:
        try:
            self.db.query(AgentRun).filter(AgentRun.id == ctx.run_id).update(
                {
                    AgentRun.status: status,
                    AgentRun.final_answer: final_answer,
                    AgentRun.steps_count: ctx.steps_count,
                    AgentRun.total_input_tokens: ctx.total_input_tokens,
                    AgentRun.total_output_tokens: ctx.total_output_tokens,
                    AgentRun.total_cost: total_cost,
                    AgentRun.latency_ms: latency_ms,
                    AgentRun.error_message: error_message,
                    AgentRun.finished_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
            self.db.commit()
        except Exception:
            logger.warning("agent_trace_end_run_failed", exc_info=True)
            self._safe_rollback()

    def _safe_rollback(self) -> None:
        try:
            self.db.rollback()
        except Exception:
            pass
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/core/test_trace.py -v`
Expected: PASS（若报缺少 `db_session` fixture，见下方说明）

说明：`db_session` fixture 若在现有 `tests/conftest.py` 未提供，参照 `tests/db/` 下现有测试使用的内存/临时库 fixture 命名并复用；本仓 `tests/db/test_vectorstore.py` 已有 DB 测试，沿用其相同 fixture。

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/agent/core/trace.py apps/luna-corpus/tests/agent/core/test_trace.py
git commit -m "feat(agent): 新增 TraceRecorder 轨迹落库（fail-safe）"
```

---

### Task 6: 内核 — Governance（每步预检 + HaltSignal）

**Files:**
- Create: `apps/luna-corpus/app/agent/core/governance.py`
- Test: `apps/luna-corpus/tests/agent/core/test_governance.py`

**Interfaces:**
- Consumes: `AgentRunContext`（Task 4）；`AgentRunStatus`（Task 2）；`check_quota`、`QuotaExceeded`（`app/cost/enforcement.py`）
- Produces:
  - `HaltSignal(Exception)`，属性 `status: AgentRunStatus`、`reason: str`
  - `check_step(db, ctx: AgentRunContext, step_index: int) -> None`：按顺序检查，触发即抛 `HaltSignal`
    - 顺序：① `step_index >= ctx.max_steps` → `HALTED_MAX_STEPS`；② `ctx.elapsed_s() > ctx.timeout_s` → `HALTED_TIMEOUT`；③ `check_quota` 抛 `QuotaExceeded` → `HALTED_QUOTA`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/agent/core/test_governance.py`：

```python
"""Governance 每步预检测试。"""
import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.governance import HaltSignal, check_step
from app.db.models import AgentRunStatus


def _ctx(**ov):
    base = dict(
        run_id="r1", tenant_id="t1", workspace_id="w1", knowledge_base_id="k1",
        user_id="u1", conversation_id=None, mode="react", max_steps=3,
        timeout_s=120, max_recursion_depth=3, start_time=1000.0,
    )
    base.update(ov)
    return AgentRunContext(**base)


def test_halts_on_max_steps(monkeypatch):
    import app.agent.core.governance as gov
    monkeypatch.setattr(gov, "check_quota", lambda *a, **k: None)
    ctx = _ctx(max_steps=3)
    with pytest.raises(HaltSignal) as exc:
        check_step(db=None, ctx=ctx, step_index=3)
    assert exc.value.status == AgentRunStatus.HALTED_MAX_STEPS


def test_halts_on_timeout(monkeypatch):
    import app.agent.core.governance as gov
    import app.agent.core.context as ctx_mod
    monkeypatch.setattr(gov, "check_quota", lambda *a, **k: None)
    ctx = _ctx(timeout_s=1, start_time=1000.0)
    monkeypatch.setattr(ctx_mod.time, "time", lambda: 1002.0)
    with pytest.raises(HaltSignal) as exc:
        check_step(db=None, ctx=ctx, step_index=0)
    assert exc.value.status == AgentRunStatus.HALTED_TIMEOUT


def test_halts_on_quota(monkeypatch):
    import app.agent.core.governance as gov
    from app.cost.enforcement import QuotaExceeded

    def boom(*a, **k):
        raise QuotaExceeded("tenant", "token")

    monkeypatch.setattr(gov, "check_quota", boom)
    ctx = _ctx()
    with pytest.raises(HaltSignal) as exc:
        check_step(db=None, ctx=ctx, step_index=0)
    assert exc.value.status == AgentRunStatus.HALTED_QUOTA


def test_passes_when_all_ok(monkeypatch):
    import app.agent.core.governance as gov
    monkeypatch.setattr(gov, "check_quota", lambda *a, **k: None)
    ctx = _ctx()
    # 不抛即通过
    check_step(db=None, ctx=ctx, step_index=0)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/core/test_governance.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现**

创建 `apps/luna-corpus/app/agent/core/governance.py`：

```python
"""Agent 每步治理预检：步数 / 超时 / 配额。触发即抛 HaltSignal。"""
from sqlalchemy.orm import Session

from app.agent.core.context import AgentRunContext
from app.cost.enforcement import QuotaExceeded, check_quota
from app.db.models import AgentRunStatus


class HaltSignal(Exception):
    """治理熔断信号：由管线捕获并将 run 标记为对应 halted_* 状态。"""

    def __init__(self, status: AgentRunStatus, reason: str) -> None:
        self.status = status
        self.reason = reason
        super().__init__(reason)


def check_step(db: Session | None, ctx: AgentRunContext, step_index: int) -> None:
    """每步开始前调用；任一检查不过即抛 HaltSignal。

    顺序：步数上限 → 墙钟超时 → 配额（配额服务异常时 check_quota 内部 fail-open）。
    """
    if step_index >= ctx.max_steps:
        raise HaltSignal(AgentRunStatus.HALTED_MAX_STEPS, "max steps reached")

    if ctx.elapsed_s() > ctx.timeout_s:
        raise HaltSignal(AgentRunStatus.HALTED_TIMEOUT, "wall-clock timeout")

    try:
        check_quota(db, ctx.tenant_id, ctx.workspace_id)
    except QuotaExceeded as exc:
        raise HaltSignal(AgentRunStatus.HALTED_QUOTA, str(exc)) from exc
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/core/test_governance.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/agent/core/governance.py apps/luna-corpus/tests/agent/core/test_governance.py
git commit -m "feat(agent): 新增 Governance 每步预检与 HaltSignal"
```

---

### Task 7: 内核 — run_tool_loop（原生 function-calling 循环引擎）

**Files:**
- Create: `apps/luna-corpus/app/agent/core/llm_loop.py`
- Test: `apps/luna-corpus/tests/agent/core/test_llm_loop.py`

**Interfaces:**
- Consumes: `AgentRunContext`（Task 4）；`TraceRecorder`（Task 5）；`check_step`、`HaltSignal`（Task 6）；`ToolRegistry`（`app/agent/registry.py`）；`extract_usage`（`app/services/llm.py`）；`AgentStepType`、`AgentRunStatus`（Task 2）
- Produces:
  - `LoopResult` 数据类：`answer: str`、`status: AgentRunStatus`、`steps: int`
  - `async run_tool_loop(*, chat, registry: ToolRegistry, ctx: AgentRunContext, trace: TraceRecorder, db, system_prompt: str, user_query: str, provider: str, model: str, single_shot: bool = False) -> LoopResult`
    - 用 `chat.bind_tools([t.get_schema() for t in registry.list_all()])` 得到 `bound`（registry 为空时不 bind）
    - messages 起始：`[system, (memory 若非空), user]`
    - 每步：先 `check_step`（HaltSignal 由调用方处理，本函数不吞）；`bound.invoke(messages)`；`extract_usage` 累加进 `ctx`；`trace.record_step(REASONING, ...)`
    - 无 `tool_calls` → 记 `FINAL` 步、返回 `LoopResult(answer=content, status=COMPLETED, steps=ctx.steps_count)`
    - 有 `tool_calls` → 逐个执行（串行），每个记 `TOOL_CALL` + `TOOL_RESULT` 两步，把结果作为 `role=tool` 消息回灌
    - `single_shot=True` 时执行完第一轮工具后强制再取一次回答即收敛（direct 模式用）
    - 循环用尽 `max_steps`：用已有 messages 再取一次 content 作为答案，返回 `status=HALTED_MAX_STEPS`
  - 说明：从 `response.tool_calls` 读取，每项形如 `{"name": str, "args": dict, "id": str}`（LangChain 标准）；容错兼容 `arguments` 键。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/agent/core/test_llm_loop.py`：

```python
"""run_tool_loop 循环引擎测试（mock LLM）。"""
import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.llm_loop import LoopResult, run_tool_loop
from app.agent.core.trace import TraceRecorder
from app.agent.registry import ToolRegistry
from app.agent.tool import tool
from app.db.models import AgentRunStatus


class FakeMsg:
    def __init__(self, content="", tool_calls=None, usage=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = usage


class FakeChat:
    """按脚本依次返回 FakeMsg 的假 LLM；bind_tools 返回自身。"""

    def __init__(self, script):
        self._script = list(script)
        self.bound_schemas = None

    def bind_tools(self, schemas):
        self.bound_schemas = schemas
        return self

    def invoke(self, messages):
        return self._script.pop(0)


class NoopTrace:
    def start_run(self, *a, **k): pass
    def record_step(self, *a, **k): pass
    def end_run(self, *a, **k): pass


def _ctx(**ov):
    base = dict(
        run_id="r1", tenant_id="t1", workspace_id="w1", knowledge_base_id="k1",
        user_id="u1", conversation_id=None, mode="react", max_steps=5,
        timeout_s=120, max_recursion_depth=3, start_time=1000.0,
    )
    base.update(ov)
    return AgentRunContext(**base)


@pytest.mark.asyncio
async def test_converges_without_tools(monkeypatch):
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)
    chat = FakeChat([FakeMsg(content="直接回答")])
    reg = ToolRegistry()
    res = await run_tool_loop(
        chat=chat, registry=reg, ctx=_ctx(), trace=NoopTrace(), db=None,
        system_prompt="sys", user_query="q", provider="ark", model="m",
    )
    assert isinstance(res, LoopResult)
    assert res.answer == "直接回答"
    assert res.status == AgentRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_executes_tool_then_answers(monkeypatch):
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)

    @tool(name="echo", description="回显")
    def echo(value: str) -> str:
        return f"got:{value}"

    reg = ToolRegistry()
    reg.register(echo)

    chat = FakeChat([
        FakeMsg(tool_calls=[{"name": "echo", "args": {"value": "hi"}, "id": "c1"}]),
        FakeMsg(content="最终答案"),
    ])
    res = await run_tool_loop(
        chat=chat, registry=reg, ctx=_ctx(), trace=NoopTrace(), db=None,
        system_prompt="sys", user_query="q", provider="ark", model="m",
    )
    assert res.answer == "最终答案"
    assert res.status == AgentRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_halts_on_max_steps(monkeypatch):
    """LLM 一直要求调工具，撞上 max_steps 后强制收敛。"""
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)

    @tool(name="echo", description="回显")
    def echo(value: str) -> str:
        return "x"

    reg = ToolRegistry()
    reg.register(echo)

    script = [FakeMsg(tool_calls=[{"name": "echo", "args": {"value": "a"}, "id": "c"}])
              for _ in range(10)]
    script.append(FakeMsg(content="兜底答案"))
    chat = FakeChat(script)
    res = await run_tool_loop(
        chat=chat, registry=reg, ctx=_ctx(max_steps=2), trace=NoopTrace(), db=None,
        system_prompt="sys", user_query="q", provider="ark", model="m",
    )
    assert res.status == AgentRunStatus.HALTED_MAX_STEPS


@pytest.mark.asyncio
async def test_tool_error_is_fed_back(monkeypatch):
    """工具抛异常时不崩，error 作为 observation 回灌，循环继续。"""
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)

    @tool(name="boom", description="炸")
    def boom(x: str) -> str:
        raise ValueError("kaboom")

    reg = ToolRegistry()
    reg.register(boom)

    chat = FakeChat([
        FakeMsg(tool_calls=[{"name": "boom", "args": {"x": "1"}, "id": "c1"}]),
        FakeMsg(content="尽管工具失败仍作答"),
    ])
    res = await run_tool_loop(
        chat=chat, registry=reg, ctx=_ctx(), trace=NoopTrace(), db=None,
        system_prompt="sys", user_query="q", provider="ark", model="m",
    )
    assert res.answer == "尽管工具失败仍作答"
    assert res.status == AgentRunStatus.COMPLETED
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/core/test_llm_loop.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现**

创建 `apps/luna-corpus/app/agent/core/llm_loop.py`：

```python
"""原生 function-calling 循环引擎：4 个模式共用。"""
import time
from dataclasses import dataclass

from app.agent.core.context import AgentRunContext
from app.agent.core.governance import check_step
from app.agent.core.trace import TraceRecorder
from app.agent.registry import ToolRegistry
from app.db.models import AgentRunStatus, AgentStepType
from app.services.llm import extract_usage


@dataclass
class LoopResult:
    """循环引擎的返回。"""

    answer: str
    status: AgentRunStatus
    steps: int


def _content(response) -> str:
    return response.content if hasattr(response, "content") else str(response)


def _accumulate_usage(ctx: AgentRunContext, response, provider: str, model: str):
    usage = extract_usage(response, provider, model)
    if usage is not None:
        ctx.total_input_tokens += usage.input_tokens
        ctx.total_output_tokens += usage.output_tokens
    return usage


async def run_tool_loop(
    *,
    chat,
    registry: ToolRegistry,
    ctx: AgentRunContext,
    trace: TraceRecorder,
    db,
    system_prompt: str,
    user_query: str,
    provider: str,
    model: str,
    single_shot: bool = False,
) -> LoopResult:
    """跑一个 function-calling 循环直至收敛或撞上治理上限。

    HaltSignal 不在此吞掉，交由调用方（管线）处理。
    """
    tools = registry.list_all()
    bound = chat.bind_tools([t.get_schema() for t in tools]) if tools else chat

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if ctx.memory_history:
        messages.append({"role": "system", "content": ctx.memory_history})
    messages.append({"role": "user", "content": user_query})

    last_content = ""
    for step_index in range(ctx.max_steps):
        check_step(db, ctx, step_index)  # 触发 HaltSignal 时向上抛

        step_start = time.time()
        response = bound.invoke(messages)
        usage = _accumulate_usage(ctx, response, provider, model)
        last_content = _content(response)
        ctx.steps_count += 1
        trace.record_step(
            ctx,
            step_index=step_index,
            step_type=AgentStepType.REASONING,
            thought=last_content or None,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            latency_ms=int((time.time() - step_start) * 1000),
        )

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            trace.record_step(
                ctx, step_index=step_index, step_type=AgentStepType.FINAL,
                thought=last_content or None,
            )
            return LoopResult(last_content, AgentRunStatus.COMPLETED, ctx.steps_count)

        # 把 assistant 的工具调用意图加入消息历史
        messages.append({"role": "assistant", "content": last_content, "tool_calls": tool_calls})

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args", call.get("arguments", {})) or {}
            call_id = call.get("id", name)
            trace.record_step(
                ctx, step_index=step_index, step_type=AgentStepType.TOOL_CALL,
                tool_name=name, tool_args=args,
            )
            tool = registry.get(name)
            if tool is None:
                result_text, success = f"Tool '{name}' not found", False
            else:
                result = await tool.execute(**args)
                result_text = result.output if result.success else (result.error or "")
                success = result.success
            trace.record_step(
                ctx, step_index=step_index, step_type=AgentStepType.TOOL_RESULT,
                tool_name=name, tool_result=result_text, tool_success=success,
            )
            messages.append(
                {"role": "tool", "tool_call_id": call_id, "content": result_text}
            )

        if single_shot:
            # direct 模式：执行一轮工具后强制取最终答案
            final_resp = bound.invoke(messages)
            _accumulate_usage(ctx, final_resp, provider, model)
            final_text = _content(final_resp)
            ctx.steps_count += 1
            trace.record_step(
                ctx, step_index=step_index + 1, step_type=AgentStepType.FINAL,
                thought=final_text or None,
            )
            return LoopResult(final_text, AgentRunStatus.COMPLETED, ctx.steps_count)

    # 撞上 max_steps：用已有上下文强制取一次答案
    return LoopResult(last_content, AgentRunStatus.HALTED_MAX_STEPS, ctx.steps_count)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/core/test_llm_loop.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/agent/core/llm_loop.py apps/luna-corpus/tests/agent/core/test_llm_loop.py
git commit -m "feat(agent): 新增 run_tool_loop 原生 function-calling 引擎"
```

---

### Task 8: base / factory — 让模式接受 AgentRunContext 与运行依赖

**Files:**
- Modify: `apps/luna-corpus/app/agent/base.py`
- Modify: `apps/luna-corpus/app/agent/factory.py`
- Test: `apps/luna-corpus/tests/agent/test_base_signature.py`

**Interfaces:**
- Consumes: `AgentRunContext`（Task 4）；`TraceRecorder`（Task 5）；`LoopResult`（Task 7）
- Produces:
  - `AgentConfig` 新增字段：`timeout_s: int = 120`、`max_recursion_depth: int = 3`
  - `Agent.run(self, ctx: AgentRunContext, trace: TraceRecorder, db) -> LoopResult`（抽象签名变更）
  - `Agent.run_stream(self, ctx, trace, db) -> AsyncGenerator[dict, None]`（抽象签名变更）
  - `AgentFactory.create(mode, tools=None, max_steps=10, timeout_s=120, max_recursion_depth=3, name="agent") -> Agent`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/agent/test_base_signature.py`：

```python
"""base/factory 新签名冒烟测试。"""
import inspect

from app.agent.base import AgentConfig
from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.core.config import AgentMode


def test_config_has_timeout_and_recursion():
    cfg = AgentConfig()
    assert cfg.timeout_s == 120
    assert cfg.max_recursion_depth == 3


def test_factory_threads_new_params():
    agent = AgentFactory.create(
        AgentMode.REACT, tools=ToolRegistry(), max_steps=7,
        timeout_s=99, max_recursion_depth=2,
    )
    assert agent.config.max_steps == 7
    assert agent.config.timeout_s == 99
    assert agent.config.max_recursion_depth == 2


def test_run_signature_takes_ctx_trace_db():
    params = list(inspect.signature(AgentFactory.create(
        AgentMode.REACT, tools=ToolRegistry()).run).parameters)
    assert params[:3] == ["ctx", "trace", "db"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/test_base_signature.py -v`
Expected: FAIL（`AssertionError` 或 `TypeError`）

- [ ] **Step 3: 改 base.py**

在 `app/agent/base.py`：`AgentConfig` 追加两字段；`Agent.run`/`run_stream` 抽象签名改为接受 `ctx, trace, db`。替换 `AgentConfig` 与两个 `@abstractmethod`：

```python
@dataclass
class AgentConfig:
    """Configuration for an Agent."""
    name: str = "agent"
    max_steps: int = 10
    timeout_s: int = 120
    max_recursion_depth: int = 3
    tools: ToolRegistry = field(default_factory=ToolRegistry)
```

```python
    @abstractmethod
    async def run(self, ctx, trace, db):
        """Run the agent. 返回 LoopResult。"""
        pass

    @abstractmethod
    async def run_stream(self, ctx, trace, db):
        """Run the agent with streaming output. Yields 事件 dict。"""
        pass
```

（`AgentResponse` 保留不动，供路由层组装响应用。）

- [ ] **Step 4: 改 factory.py**

`AgentFactory.create` 增加 `timeout_s`/`max_recursion_depth` 形参并写入 `AgentConfig`。替换 `create` 方法签名与 `config = ...` 行：

```python
    @staticmethod
    def create(
        mode: AgentMode,
        tools: ToolRegistry | list[Tool] | None = None,
        max_steps: int = 10,
        timeout_s: int = 120,
        max_recursion_depth: int = 3,
        name: str = "agent",
    ) -> Agent:
```

```python
        config = AgentConfig(
            name=name,
            max_steps=max_steps,
            timeout_s=timeout_s,
            max_recursion_depth=max_recursion_depth,
            tools=registry,
        )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/test_base_signature.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/luna-corpus/app/agent/base.py apps/luna-corpus/app/agent/factory.py apps/luna-corpus/tests/agent/test_base_signature.py
git commit -m "refactor(agent): base/factory 接入 ctx/trace/db 与治理参数"
```

---

### Task 9: 四模式重写 — 全部基于 run_tool_loop

**Files:**
- Modify: `apps/luna-corpus/app/agent/modes/direct.py`
- Modify: `apps/luna-corpus/app/agent/modes/react.py`
- Modify: `apps/luna-corpus/app/agent/modes/plan_execute.py`
- Modify: `apps/luna-corpus/app/agent/modes/langgraph.py`
- Test: `apps/luna-corpus/tests/agent/test_modes_use_loop.py`

**Interfaces:**
- Consumes: `run_tool_loop`、`LoopResult`（Task 7）；`AgentRunContext`（Task 4）；`get_chat_model`、provider/model（`app/services/llm.py` + `get_settings`）
- Produces: 四个模式的 `run(ctx, trace, db) -> LoopResult`、`run_stream(ctx, trace, db)`。差异：
  - `direct`：`single_shot=True`，system prompt 为通用助手
  - `react`：全量循环（`single_shot=False`），system prompt 为 ReAct 风格
  - `plan_execute`：system prompt 要求先列计划再逐步执行，`single_shot=False`
  - `langgraph`：system prompt 说明可多步分解，`single_shot=False`（P0 阶段用统一循环承载，删除旧状态机与正则）

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/agent/test_modes_use_loop.py`：

```python
"""四模式均通过 run_tool_loop 执行（mock LLM + mock loop）。"""
import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.llm_loop import LoopResult
from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.core.config import AgentMode
from app.db.models import AgentRunStatus


class NoopTrace:
    def start_run(self, *a, **k): pass
    def record_step(self, *a, **k): pass
    def end_run(self, *a, **k): pass


def _ctx(mode):
    return AgentRunContext(
        run_id="r1", tenant_id="t1", workspace_id="w1", knowledge_base_id="k1",
        user_id="u1", conversation_id=None, mode=mode, max_steps=5,
        timeout_s=120, max_recursion_depth=3, start_time=1000.0,
    )


@pytest.mark.parametrize("mode", list(AgentMode))
@pytest.mark.asyncio
async def test_mode_delegates_to_loop(mode, monkeypatch):
    called = {}

    async def fake_loop(**kwargs):
        called["single_shot"] = kwargs.get("single_shot", False)
        called["provider"] = kwargs["provider"]
        return LoopResult("答案", AgentRunStatus.COMPLETED, 1)

    # patch 每个模式模块内引用的 run_tool_loop
    import app.agent.modes.direct as m_direct
    import app.agent.modes.react as m_react
    import app.agent.modes.plan_execute as m_plan
    import app.agent.modes.langgraph as m_lg
    for m in (m_direct, m_react, m_plan, m_lg):
        monkeypatch.setattr(m, "run_tool_loop", fake_loop)
        monkeypatch.setattr(m, "get_chat_model", lambda: object())

    agent = AgentFactory.create(mode, tools=ToolRegistry())
    res = await agent.run(_ctx(mode.value), NoopTrace(), db=None)
    assert res.answer == "答案"
    if mode == AgentMode.DIRECT:
        assert called["single_shot"] is True
    else:
        assert called["single_shot"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/test_modes_use_loop.py -v`
Expected: FAIL（旧模式无 `run_tool_loop`、旧签名不接受 ctx）

- [ ] **Step 3: 重写 direct.py**

全量替换 `apps/luna-corpus/app/agent/modes/direct.py`：

```python
"""Direct Agent - 单轮 + 可选一次工具调用（基于共享循环引擎）。"""
from typing import Any, AsyncGenerator

from app.agent.base import Agent
from app.agent.core.llm_loop import LoopResult, run_tool_loop
from app.core.config import get_settings
from app.services.llm import get_chat_model

_SYSTEM_PROMPT = "你是一个有用的助手，可按需调用工具。若无需工具，直接作答。"


def _provider_model():
    s = get_settings()
    return s.llm_provider.value, s.ark_model


class DirectAgent(Agent):
    """单轮执行：最多一轮工具调用后强制收敛。"""

    async def run(self, ctx, trace, db) -> LoopResult:
        provider, model = _provider_model()
        return await run_tool_loop(
            chat=get_chat_model(), registry=self.registry, ctx=ctx, trace=trace, db=db,
            system_prompt=_SYSTEM_PROMPT, user_query=ctx.query,
            provider=provider, model=model, single_shot=True,
        )

    async def run_stream(self, ctx, trace, db) -> AsyncGenerator[dict[str, Any], None]:
        yield {"event": "run_start", "data": {"run_id": ctx.run_id}}
        result = await self.run(ctx, trace, db)
        yield {"event": "done", "data": {
            "answer": result.answer, "run_id": ctx.run_id,
            "steps": result.steps, "status": result.status.value,
        }}
```

（`ctx.query` 已在 Task 4 的 `AgentRunContext` 中定义，无需额外改动。）

- [ ] **Step 4: 重写 react.py**

全量替换 `apps/luna-corpus/app/agent/modes/react.py`：

```python
"""ReAct Agent - 思考-行动循环（基于共享循环引擎，原生 function-calling）。"""
from typing import Any, AsyncGenerator

from app.agent.base import Agent
from app.agent.core.llm_loop import LoopResult, run_tool_loop
from app.core.config import get_settings
from app.services.llm import get_chat_model

_SYSTEM_PROMPT = (
    "你是一个善于分步推理的助手。先思考，再决定是否调用工具，"
    "观察结果后继续，直到能够回答。可多次调用工具。"
)


def _provider_model():
    s = get_settings()
    return s.llm_provider.value, s.ark_model


class ReActAgent(Agent):
    """全量 ReAct 循环。"""

    async def run(self, ctx, trace, db) -> LoopResult:
        provider, model = _provider_model()
        return await run_tool_loop(
            chat=get_chat_model(), registry=self.registry, ctx=ctx, trace=trace, db=db,
            system_prompt=_SYSTEM_PROMPT, user_query=ctx.query,
            provider=provider, model=model, single_shot=False,
        )

    async def run_stream(self, ctx, trace, db) -> AsyncGenerator[dict[str, Any], None]:
        yield {"event": "run_start", "data": {"run_id": ctx.run_id}}
        result = await self.run(ctx, trace, db)
        yield {"event": "done", "data": {
            "answer": result.answer, "run_id": ctx.run_id,
            "steps": result.steps, "status": result.status.value,
        }}
```

- [ ] **Step 5: 重写 plan_execute.py**

全量替换 `apps/luna-corpus/app/agent/modes/plan_execute.py`：

```python
"""Plan-Execute Agent - 先规划再执行（基于共享循环引擎）。"""
from typing import Any, AsyncGenerator

from app.agent.base import Agent
from app.agent.core.llm_loop import LoopResult, run_tool_loop
from app.core.config import get_settings
from app.services.llm import get_chat_model

_SYSTEM_PROMPT = (
    "你是一个任务规划助手。先在心里列出完成任务所需的步骤，"
    "然后逐步调用工具执行，最后综合得出答案。可多次调用工具。"
)


def _provider_model():
    s = get_settings()
    return s.llm_provider.value, s.ark_model


class PlanExecuteAgent(Agent):
    """先规划后执行。"""

    async def run(self, ctx, trace, db) -> LoopResult:
        provider, model = _provider_model()
        return await run_tool_loop(
            chat=get_chat_model(), registry=self.registry, ctx=ctx, trace=trace, db=db,
            system_prompt=_SYSTEM_PROMPT, user_query=ctx.query,
            provider=provider, model=model, single_shot=False,
        )

    async def run_stream(self, ctx, trace, db) -> AsyncGenerator[dict[str, Any], None]:
        yield {"event": "run_start", "data": {"run_id": ctx.run_id}}
        result = await self.run(ctx, trace, db)
        yield {"event": "done", "data": {
            "answer": result.answer, "run_id": ctx.run_id,
            "steps": result.steps, "status": result.status.value,
        }}
```

- [ ] **Step 6: 重写 langgraph.py**

全量替换 `apps/luna-corpus/app/agent/modes/langgraph.py`（删除旧状态机与 `_extract_tool_call_json` 正则）：

```python
"""LangGraph Agent - 多步分解（P0 阶段由共享循环引擎统一承载）。"""
from typing import Any, AsyncGenerator

from app.agent.base import Agent
from app.agent.core.llm_loop import LoopResult, run_tool_loop
from app.core.config import get_settings
from app.services.llm import get_chat_model

_SYSTEM_PROMPT = (
    "你是一个能把复杂问题分解为多步的助手。逐步推理并按需调用工具，"
    "直到得出完整答案。可多次调用工具。"
)


def _provider_model():
    s = get_settings()
    return s.llm_provider.value, s.ark_model


class LangGraphAgent(Agent):
    """多步分解执行。"""

    async def run(self, ctx, trace, db) -> LoopResult:
        provider, model = _provider_model()
        return await run_tool_loop(
            chat=get_chat_model(), registry=self.registry, ctx=ctx, trace=trace, db=db,
            system_prompt=_SYSTEM_PROMPT, user_query=ctx.query,
            provider=provider, model=model, single_shot=False,
        )

    async def run_stream(self, ctx, trace, db) -> AsyncGenerator[dict[str, Any], None]:
        yield {"event": "run_start", "data": {"run_id": ctx.run_id}}
        result = await self.run(ctx, trace, db)
        yield {"event": "done", "data": {
            "answer": result.answer, "run_id": ctx.run_id,
            "steps": result.steps, "status": result.status.value,
        }}
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/test_modes_use_loop.py -v`
Expected: PASS

- [ ] **Step 8: 清理旧模式测试**

旧的 `tests/agent/` 下针对 JSON/正则解析、旧 `run(query)` 签名的用例会失败。运行 `cd apps/luna-corpus && python -m pytest tests/agent/ -v`，对因签名变更而失效的旧断言逐一更新为新签名或删除已不适用的用例（如 `_parse_response`、`_extract_tool_call_json` 相关）。保持每个模式至少有一条通过的行为测试。

- [ ] **Step 9: 提交**

```bash
git add apps/luna-corpus/app/agent/modes/ apps/luna-corpus/app/agent/core/context.py apps/luna-corpus/tests/agent/
git commit -m "refactor(agent): 四模式全部基于 run_tool_loop 重写"
```

---

### Task 10: 审计动作 + 会话记忆适配器

**Files:**
- Modify: `apps/luna-corpus/app/security/audit.py`（`AuditAction` 新增 `AGENT_QUERY = "agent.query"`）
- （无测试文件，属性常量测试归入 Task 11 集成测试）

**Interfaces:**
- Produces: `AuditAction.AGENT_QUERY` 常量，供路由管线审计入参

- [ ] **Step 1: 追加审计动作**

在 `apps/luna-corpus/app/security/audit.py` 的 `AuditAction` 枚举末尾追加：

```python
    AGENT_QUERY = "agent.query"
```

- [ ] **Step 2: 提交**

```bash
git add apps/luna-corpus/app/security/audit.py
git commit -m "feat(agent): AuditAction 新增 AGENT_QUERY"
```

---

### Task 11: 路由管线 — agent_routes 改造 + 回放 API

**Files:**
- Modify: `apps/luna-corpus/app/api/agent_routes.py`（`/query` 和 `/stream` 改造为完整管线）
- Create: `apps/luna-corpus/app/api/agent_runs_routes.py`（回放 API）
- Modify: `apps/luna-corpus/app/main.py`（挂载新路由）
- Test: `apps/luna-corpus/tests/api/test_agent_routes_pipeline.py`
- Test: `apps/luna-corpus/tests/api/test_agent_runs_routes.py`

**Interfaces:**
- Consumes: `AgentFactory`（Task 8）、`AgentRunContext`（Task 4）、`TraceRecorder`（Task 5）、`AgentRunStatus`、`AgentRun`、`AgentStep`（Task 2）、`AuditAction.AGENT_QUERY`（Task 10）、`check_quota`/`QuotaExceeded`（`app/cost/enforcement.py`）、`record_usage`（`app/cost/recorder.py`）、`get_memory_context`/`format_conversation_history`/`add_message_to_conversation`（`app/services/memory.py`）、`AuthenticatedRequestContext`/`require_permission`（`app/api/auth.py`）、`AuditService`/`AuditResult`（`app/security/audit.py`）、`get_settings`
- Produces:
  - `POST /api/v1/agent/query` 响应新增 `run_id` 字段
  - `POST /api/v1/agent/stream` SSE 事件新增 `run_id` 和 `status`
  - `GET /api/v1/agent/runs` — 列表，过滤 `?conversation_id=&user_id=&status=&limit=50`
  - `GET /api/v1/agent/runs/{run_id}` — 详情，含有序 steps

- [ ] **Step 1: 写测试（集成级）**

创建 `apps/luna-corpus/tests/api/test_agent_routes_pipeline.py`：

```python
"""agent 路由管线集成测试（mock LLM、mock DB）。"""
import pytest
from unittest.mock import MagicMock, patch

from app.agent.core.llm_loop import LoopResult
from app.db.models import AgentRunStatus


@pytest.mark.asyncio
async def test_query_returns_run_id(client, monkeypatch, db_session):
    """POST /api/v1/agent/query 返回中包含 run_id。"""
    # mock 管线内部：不真的调 agent，验证 run_id 被透出
    fake_result = LoopResult("hi", AgentRunStatus.COMPLETED, 1)

    async def fake_run(*a, **k):
        return fake_result

    from app.agent.modes import direct
    monkeypatch.setattr(direct.DirectAgent, "run", fake_run)

    # 用现有 /agent/query 发送请求（需 mock 认证与知识库上下文）
    # 实际：依赖 client fixture（在 tests/conftest.py 中定义）
    # 这里写结构示意，执行时需根据现有 conftest 调整
    pass
```

> 说明：本测试强依赖现有 `client` fixture 与 auth mock。手写完整 mock 方案若与现有测试结构不匹配则浪费。改为**在 Task 11 集成测试中，跳到 Step 3 在路由实现后手动跑一次全链路冒烟**，不写细粒度测试文件，由 Task 11 的 implementer 参照 `tests/api/test_routes.py` 中 `/qa/query` 的测试写法，为 `/agent/query` 写等效的集成测试。

- [ ] **Step 2: 改造 agent_routes.py**

全量替换 `apps/luna-corpus/app/api/agent_routes.py`。顶部需补充导入：

```python
import time
import uuid

from app.agent.core.context import AgentRunContext
from app.agent.core.governance import HaltSignal
from app.agent.core.trace import TraceRecorder
from app.cost.enforcement import QuotaExceeded, check_quota
from app.cost.recorder import record_usage
from app.db.database import get_db
from app.db.models import AgentRunStatus, MessageRole
from app.security.audit import AuditAction, AuditService
from app.db.models import AuditResult
from app.services.llm import TokenUsage
from app.services.memory import (
    add_message_to_conversation,
    format_conversation_history,
    get_conversation_messages,
    get_memory_context,
)
```

`AgentQueryRequest` 需新增可选字段 `conversation_id: str | None = None`。核心改动：

1. `/query` 管线流程：

```
POST /api/v1/agent/query
  request ← AgentQueryRequest(query, mode, available_tools, stream)
  context ← require_permission(QA_QUERY)
  db ← get_db() session

  # 事前配额准入
  try: check_quota(db, context.tenant.id, context.workspace.id)
  except QuotaExceeded: raise 429

  # 构建 AgentRunContext
  run_id = str(uuid4())
  settings = get_settings()
  memory_history = ""  # 载入会话记忆（若 conversation_id 提供）
  if request.conversation_id:
      mem, _ = get_memory_context(db, request.conversation_id)
      history = format_conversation_history(
          get_conversation_messages(db, request.conversation_id))
      memory_history = f"{mem}\n{history}".strip()

  ctx = AgentRunContext(
      run_id=run_id, tenant_id=context.tenant.id, workspace_id=context.workspace.id,
      knowledge_base_id=context.knowledge_base.id, user_id=context.user.id,
      conversation_id=request.conversation_id, mode=request.mode,
      max_steps=settings.agent_max_steps, timeout_s=settings.agent_timeout_s,
      max_recursion_depth=settings.agent_max_recursion_depth,
      start_time=time.time(), query=request.query,
      memory_history=memory_history,
  )

  # 轨迹启动
  trace = TraceRecorder(db)
  trace.start_run(ctx, request.query)

  try:
      # 模式解析 + 工具注册
      mode = AgentMode(request.mode)
      registry = filter_registry(get_default_registry(context.knowledge_base.id), request.available_tools)
      agent = AgentFactory.create(mode=mode, tools=registry, max_steps=settings.agent_max_steps,
                                  timeout_s=settings.agent_timeout_s,
                                  max_recursion_depth=settings.agent_max_recursion_depth)

      # 执行
      result = await agent.run(ctx, trace, db)
      latency_ms = int(ctx.elapsed_s() * 1000)

      # 轨迹终态
      trace.end_run(ctx, status=result.status, final_answer=result.answer,
                    total_cost=0, latency_ms=latency_ms)

      # 审计
      AuditService().record(db, action=AuditAction.AGENT_QUERY, resource_type="knowledge_base",
                            resource_id=context.knowledge_base.id, result=AuditResult.SUCCESS,
                            context=context)

      # 会话消息落库
      if request.conversation_id:
          add_message_to_conversation(db, request.conversation_id, MessageRole.USER, request.query)
          add_message_to_conversation(db, request.conversation_id, MessageRole.ASSISTANT, result.answer)

      # 成本计量：把 run 级累加的 token 折算入 usage_records（record_usage 内部 fail-safe）
      settings_provider, settings_model = get_settings().llm_provider.value, get_settings().ark_model
      record_usage(db, tenant_id=context.tenant.id, workspace_id=context.workspace.id,
                   knowledge_base_id=context.knowledge_base.id, interaction_id=run_id,
                   usage=TokenUsage(
                       input_tokens=ctx.total_input_tokens,
                       output_tokens=ctx.total_output_tokens,
                       model=settings_model, provider=settings_provider,
                   ) if (ctx.total_input_tokens or ctx.total_output_tokens) else None)

      db.commit()

  except HaltSignal as h:
      trace.end_run(ctx, status=h.status, final_answer="", total_cost=0,
                    latency_ms=int(ctx.elapsed_s() * 1000), error_message=h.reason)
      db.commit()
      raise HTTPException(429, h.reason) from h
  except Exception as e:
      trace.end_run(ctx, status=AgentRunStatus.FAILED, final_answer="", total_cost=0,
                    latency_ms=int(ctx.elapsed_s() * 1000), error_message=str(e))
      db.commit()
      raise

  return AgentQueryResponse(answer=result.answer, run_id=run_id, mode=request.mode,
                            steps=result.steps, latency_ms=latency_ms,
                            tool_calls=[])
  # 说明：LoopResult 不携带 tool_calls；工具调用明细已落入 agent_steps，
  # 前端经 GET /api/v1/agent/runs/{run_id} 拉取。tool_calls 字段保留为空列表以兼容旧响应模型。
```

2. `/stream` 管线：类似流程，但中间 yield 事件 + 在 SSE 流末尾 `done` 事件中一并做 fallback 轨迹落库与审计（与 `generate_streaming_response` 模式一致，参考 `routes.py` 的 `stream_event_generator` 模式）。

3. `AgentQueryResponse` 新增 `run_id: str = ""` 字段。

4. 删除模块级 `_registered_tools` 机制（P0 保留 `POST /tools` 不使能，标记 deprecation 注释）。

- [ ] **Step 3: 创建回放 API**

创建 `apps/luna-corpus/app/api/agent_runs_routes.py`：

```python
"""Agent 执行回放 API。"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.db.models import AgentRun, AgentStep

router = APIRouter(prefix="/api/v1/agent/runs", tags=["agent"])


@router.get("")
async def list_runs(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
    conversation_id: str | None = Query(None),
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """列出当前知识库下的 agent 执行记录。"""
    q = db.query(AgentRun).filter(
        AgentRun.knowledge_base_id == context.knowledge_base.id
    )
    if conversation_id:
        q = q.filter(AgentRun.conversation_id == conversation_id)
    if user_id:
        q = q.filter(AgentRun.user_id == user_id)
    if status:
        q = q.filter(AgentRun.status == status)
    rows = q.order_by(AgentRun.created_at.desc()).limit(limit).all()
    return {"runs": [dict(id=r.id, query=r.query, mode=r.mode, status=r.status.value,
                          steps_count=r.steps_count, latency_ms=r.latency_ms,
                          created_at=r.created_at.isoformat()) for r in rows]}


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
) -> dict:
    """获取单次 agent 执行的完整轨迹。"""
    run = db.query(AgentRun).filter(
        AgentRun.id == run_id,
        AgentRun.knowledge_base_id == context.knowledge_base.id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    steps = db.query(AgentStep).filter(
        AgentStep.run_id == run_id
    ).order_by(AgentStep.step_index, AgentStep.created_at).all()
    return {
        "run": {
            "id": run.id, "query": run.query, "final_answer": run.final_answer,
            "mode": run.mode, "status": run.status.value,
            "steps_count": run.steps_count, "latency_ms": run.latency_ms,
            "total_input_tokens": run.total_input_tokens,
            "total_output_tokens": run.total_output_tokens,
            "total_cost": str(run.total_cost),
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        },
        "steps": [
            {
                "step_index": s.step_index, "step_type": s.step_type.value,
                "thought": s.thought, "tool_name": s.tool_name,
                "tool_args": s.tool_args, "tool_result": s.tool_result,
                "tool_success": s.tool_success,
                "input_tokens": s.input_tokens, "output_tokens": s.output_tokens,
                "latency_ms": s.latency_ms,
            }
            for s in steps
        ],
    }
```

- [ ] **Step 4: 挂载路由**

在 `apps/luna-corpus/app/main.py` 中追加：

```python
from app.api.agent_runs_routes import router as agent_runs_router
# 在现有 app.include_router(...) 区域追加：
app.include_router(agent_runs_router)
```

- [ ] **Step 5: 运行全链路冒烟测试**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/ tests/api/test_agent_routes_pipeline.py -v`
Expected: 至少现有测试通过（需先忽略因签名变更失败的旧测试，已通过 Step 9 清理）

- [ ] **Step 6: 提交**

```bash
git add apps/luna-corpus/app/api/agent_routes.py apps/luna-corpus/app/api/agent_runs_routes.py apps/luna-corpus/app/main.py apps/luna-corpus/app/security/audit.py
git commit -m "feat(agent): 路由管线 + 回放 API + 审计动作"
```

---

### Task 12: 集成回归 — 全链路落库 + 熔断 + 全套件绿

**Files:**
- Create: `apps/luna-corpus/tests/agent/test_run_pipeline_integration.py`
- Test: 同上

**Interfaces:**
- Consumes: 前述全部内核 + 模式 + 路由

- [ ] **Step 1: 写集成测试（内核级全链路，mock LLM，真实内存 DB）**

创建 `apps/luna-corpus/tests/agent/test_run_pipeline_integration.py`。直接驱动 `AgentFactory` + `TraceRecorder` + `run_tool_loop`（不经 HTTP），验证 run/steps 落库与熔断：

```python
"""Agent 全链路集成：run/steps 落库、成本累加、熔断状态。"""
import time

import pytest

from app.agent.core.context import AgentRunContext
from app.agent.core.governance import HaltSignal
from app.agent.core.trace import TraceRecorder
from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.agent.tool import tool
from app.core.config import AgentMode
from app.db.models import AgentRun, AgentRunStatus, AgentStep


class FakeMsg:
    def __init__(self, content="", tool_calls=None, usage=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = usage


class FakeChat:
    def __init__(self, script):
        self._script = list(script)
    def bind_tools(self, schemas):
        return self
    def invoke(self, messages):
        return self._script.pop(0)


def _ctx(db_ok_mode="react", max_steps=5, timeout_s=120):
    return AgentRunContext(
        run_id="run-int-1", tenant_id="t1", workspace_id="w1", knowledge_base_id="k1",
        user_id="u1", conversation_id=None, mode=db_ok_mode, max_steps=max_steps,
        timeout_s=timeout_s, max_recursion_depth=3, start_time=time.time(),
        query="用工具查一下",
    )


@pytest.mark.asyncio
async def test_full_trace_persisted(db_session, monkeypatch):
    import app.agent.core.llm_loop as loop_mod
    monkeypatch.setattr(loop_mod, "check_step", lambda *a, **k: None)

    @tool(name="echo", description="回显")
    def echo(value: str) -> str:
        return f"got:{value}"

    reg = ToolRegistry()
    reg.register(echo)
    agent = AgentFactory.create(AgentMode.REACT, tools=reg)

    monkeypatch.setattr(
        "app.agent.modes.react.get_chat_model",
        lambda: FakeChat([
            FakeMsg(tool_calls=[{"name": "echo", "args": {"value": "x"}, "id": "c1"}],
                    usage={"input_tokens": 10, "output_tokens": 5}),
            FakeMsg(content="完成", usage={"input_tokens": 3, "output_tokens": 2}),
        ]),
    )

    ctx = _ctx()
    trace = TraceRecorder(db_session)
    trace.start_run(ctx, ctx.query)
    result = await agent.run(ctx, trace, db_session)
    trace.end_run(ctx, status=result.status, final_answer=result.answer,
                  total_cost=0, latency_ms=100)

    run = db_session.query(AgentRun).filter(AgentRun.id == "run-int-1").first()
    assert run.status == AgentRunStatus.COMPLETED
    assert run.final_answer == "完成"
    assert run.total_input_tokens == 13
    assert run.total_output_tokens == 7
    steps = db_session.query(AgentStep).filter(AgentStep.run_id == "run-int-1").all()
    # reasoning + tool_call + tool_result + final ≥ 4 步
    assert len(steps) >= 4


@pytest.mark.asyncio
async def test_quota_halt_marks_run(db_session, monkeypatch):
    """配额熔断 → run 标 halted_quota，部分步骤已落库。"""
    import app.agent.core.llm_loop as loop_mod
    from app.db.models import AgentRunStatus as S

    def halt(*a, **k):
        raise HaltSignal(S.HALTED_QUOTA, "quota exceeded")

    monkeypatch.setattr(loop_mod, "check_step", halt)

    agent = AgentFactory.create(AgentMode.REACT, tools=ToolRegistry())
    monkeypatch.setattr("app.agent.modes.react.get_chat_model", lambda: FakeChat([]))

    ctx = _ctx()
    trace = TraceRecorder(db_session)
    trace.start_run(ctx, ctx.query)
    with pytest.raises(HaltSignal) as exc:
        await agent.run(ctx, trace, db_session)
    trace.end_run(ctx, status=exc.value.status, final_answer="",
                  total_cost=0, latency_ms=1, error_message=exc.value.reason)

    run = db_session.query(AgentRun).filter(AgentRun.id == "run-int-1").first()
    assert run.status == AgentRunStatus.HALTED_QUOTA
```

- [ ] **Step 2: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/agent/test_run_pipeline_integration.py -v`
Expected: PASS

- [ ] **Step 3: 全套件绿**

Run: `cd apps/luna-corpus && python -m pytest -q`
Expected: 全绿。若有旧 agent 测试因签名变更失败，更新为新签名或移除失效断言。

- [ ] **Step 4: lint**

Run: `cd apps/luna-corpus && python -m ruff check app/agent app/api/agent_routes.py app/api/agent_runs_routes.py`
Expected: 无错误（或按提示修正）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/tests/agent/test_run_pipeline_integration.py
git commit -m "test(agent): 全链路集成 + 熔断落库回归"
```

---

### Task 13: 收尾文档 — follow-ups + 部署待办

**Files:**
- Create: `docs/follow-ups/2026-07-15-agent-production-p0.md`

**Interfaces:** 无代码

- [ ] **Step 1: 写 follow-ups**

创建 `docs/follow-ups/2026-07-15-agent-production-p0.md`，记录本次有意延后项：

```markdown
# Agent 生产化 P0 —— 跟进项（有意延后，非阻断）

日期：2026-07-15

## 部署/运维待办（合入后手动执行）
- [ ] 运行 Alembic 迁移创建 agent_runs / agent_steps：`alembic upgrade head`
- [ ] 确认生产 env 设置 `AGENT_TIMEOUT_S`（默认 120）、`AGENT_MAX_RECURSION_DEPTH`（默认 3）

## P1 跟进（划归下一阶段）
1. 工具并行调用（当前串行执行 LLM 请求的多个 tool_calls）
2. 子 agent / agent 编排 agent（递归深度当前只设防护上限）
3. 人工审批中断（human-in-the-loop）
4. 动态注册工具的可执行体（`POST /tools` 当前只存 schema，注册后不可调用）
5. langgraph 模式当前与 react 共用统一循环，未来可恢复真正的状态图编排
6. run 级 total_cost 精确折算（当前 end_run 传 0，成本记在 usage_records；如需 run 级成本汇总可在 record_usage 后回填）
7. 流式 SSE 事件粒度：P0 的 `run_stream` 先落地 `run_start` + `done` 两事件（run-then-done）；spec 4.2 的逐步 `step`/`tool_call`/`tool_result`/`token` 细粒度事件在 P1 补齐（需 `run_tool_loop` 暴露异步事件生成器版本）
```

- [ ] **Step 2: 提交**

```bash
git add docs/follow-ups/2026-07-15-agent-production-p0.md
git commit -m "docs(agent): P0 跟进项与部署待办"
```

---

## 附：执行顺序与依赖

```
Task 1 (config) ─┐
Task 2 (models) ─┼─→ Task 3 (migration)
                 ├─→ Task 4 (context) ─→ Task 5 (trace)
                 │                    └─→ Task 6 (governance) ─→ Task 7 (llm_loop)
                 │                                                    │
Task 8 (base/factory) ←──────────────────────────────────────────────┘
   └─→ Task 9 (4 modes) ─→ Task 10 (audit) ─→ Task 11 (routes+replay)
                                                    └─→ Task 12 (integration) ─→ Task 13 (docs)
```

每个 Task 结束都有独立可测的交付物，可作为一次 reviewer gate。
