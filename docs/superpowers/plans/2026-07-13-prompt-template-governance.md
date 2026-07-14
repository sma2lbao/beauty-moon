# Prompt 与模板治理（A/B 实验版）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 RAG 主问答提示词从硬编码收敛为「文件保底 + 数据库实验版本」的可管理资产，按知识库配置 A/B 实验、稳定哈希分流，并与质量评估模块联动做每指标独立的显著性检验。

**Architecture:** 新建 `app/prompts/` 模块（registry 加载 / experiment 分流 / stats 统计 / schemas），`services/prompt_builder.py` 改为「选版本→取模板→渲染」解耦。新增 2 张零耦合表 + `QAInteraction` 加一列记录命中版本。报告 API 复用现有 quality 聚合表按版本分组并跑显著性。全链路 fail-safe：治理逻辑任何异常都回退文件默认模板，问答绝不失败。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy 2.0（Mapped/mapped_column）、Alembic、pytest。统计检验纯标准库（`math` + `statistics`），不引入 numpy/scipy。

## Global Constraints

- 包管理器统一 `npm`；测试通过 `npm exec nx` 或直接 `pytest`（工作目录 `apps/luna-corpus`）运行。
- **不新增第三方依赖**：项目 `pyproject.toml` 刻意精简，统计用标准库实现；文件默认模板用 **Python 常量模块**（非 YAML，因项目无 yaml 依赖）。
- 本期范围**仅** RAG 主问答提示词（`prompt_key = "rag_qa"`，中英双语 `zh`/`en`）；不动 agent 各模式与 `judge.py`。
- fail-safe 风格与现有 `recorder.py` 一致：治理侧任何异常 → 记 warning 日志 + 回退默认 + `prompt_version_id=None`，绝不让问答请求失败。
- ID 主键统一 `CHAR(36)` UUID，模式对齐现有 `app/db/models.py`（`Mapped[...]` + `mapped_column`，`created_at` 用 `server_default=func.now()`）。
- 迁移沿用惯例「待手动跑」；迁移 revision 命名 `20260713_0012`，`down_revision = "20260713_0011"`。
- 所有代码路径均在 `apps/luna-corpus/` 下（下文路径省略该前缀）。

---

## 文件结构

**新建：**
- `app/prompts/__init__.py` — 模块导出
- `app/prompts/schemas.py` — Pydantic/dataclass 结构（模板、实验配置、分流结果、统计结论）
- `app/prompts/stats.py` — Welch's t-test + 双比例 z-test，纯函数
- `app/prompts/defaults.py` — 文件保底模板（Python 常量），rag_qa 中英文
- `app/prompts/registry.py` — 模板加载：文件默认层 + DB 覆盖层 + 内存缓存
- `app/prompts/experiment.py` — 稳定哈希分流 + select_version
- `app/prompts/report.py` — 按版本聚合 + 组装显著性对比报告
- `alembic/versions/20260713_0012_prompt_governance.py` — 迁移
- 测试：`tests/prompts/__init__.py`、`test_stats.py`、`test_registry.py`、`test_experiment.py`、`test_report.py`、`test_prompt_models.py`、`tests/api/test_prompt_experiment_api.py`

**修改：**
- `app/db/models.py` — 新增 2 表 + 3 枚举；`QAInteraction` 加 `prompt_version_id` 列
- `app/services/prompt_builder.py` — 接受 `template_text`，渲染与选择解耦
- `app/graph/state.py` — `RAGState` 加 `prompt_version_id` 输出键
- `app/graph/rag_graph.py` — `generate_node` 选版本并回填；`answer_question*` result 带出 `prompt_version_id`
- `app/api/routes.py` — `record_interaction` 传入 `prompt_version_id`；新增实验管理与报告端点
- `app/quality/recorder.py` — `record_interaction` 增 `prompt_version_id` 参数
- `app/auth/permissions.py` — 新增 `PROMPT_MANAGE` 权限并授予管理角色

---

### Task 1: 统计函数库 `stats.py`

纯函数，无 DB/IO。先做它，因为报告 API 依赖它，且最易 TDD 对拍。

**Files:**
- Create: `app/prompts/stats.py`
- Test: `tests/prompts/__init__.py`（空文件）、`tests/prompts/test_stats.py`

**Interfaces:**
- Produces:
  - `@dataclass TTestResult`：字段 `p_value: float | None`、`diff: float | None`、`ci95: tuple[float, float] | None`、`insufficient: bool`
  - `@dataclass ZTestResult`：字段同上（`diff` 为比例差）
  - `def welch_t_test(a: list[float], b: list[float]) -> TTestResult`（a=baseline, b=variant, diff = mean(b) - mean(a)，双尾）
  - `def two_proportion_z_test(up_a: int, n_a: int, up_b: int, n_b: int) -> ZTestResult`（diff = p_b - p_a，双尾）
  - `MIN_SAMPLE = 30`

- [ ] **Step 1: 写失败测试**

```python
# tests/prompts/test_stats.py
import math

from app.prompts.stats import (
    MIN_SAMPLE,
    two_proportion_z_test,
    welch_t_test,
)


def test_welch_t_test_clear_difference():
    # 两组均值差异明显，方差小 → 应显著 (p < 0.05)，diff>0
    a = [0.50, 0.52, 0.48, 0.51, 0.49] * 8  # n=40, mean≈0.50
    b = [0.70, 0.72, 0.68, 0.71, 0.69] * 8  # n=40, mean≈0.70
    res = welch_t_test(a, b)
    assert res.insufficient is False
    assert res.p_value is not None and res.p_value < 0.05
    assert res.diff is not None and 0.18 < res.diff < 0.22
    lo, hi = res.ci95
    assert lo < res.diff < hi


def test_welch_t_test_no_difference():
    a = [0.60, 0.62, 0.58, 0.61, 0.59] * 8
    b = [0.60, 0.62, 0.58, 0.61, 0.59] * 8
    res = welch_t_test(a, b)
    assert res.insufficient is False
    assert res.p_value is not None and res.p_value > 0.05
    assert abs(res.diff) < 1e-9


def test_welch_t_test_insufficient_sample():
    res = welch_t_test([0.5] * 10, [0.6] * 40)
    assert res.insufficient is True
    assert res.p_value is None


def test_welch_t_test_zero_variance_no_crash():
    # 两组各自方差为 0 但均值不同：不应除零崩溃
    res = welch_t_test([0.5] * 40, [0.5] * 40)
    assert res.insufficient is False
    assert res.diff == 0.0


def test_two_proportion_z_clear_difference():
    # A: 30/100 好评, B: 70/100 好评 → 显著
    res = two_proportion_z_test(up_a=30, n_a=100, up_b=70, n_b=100)
    assert res.insufficient is False
    assert res.p_value is not None and res.p_value < 0.05
    assert res.diff is not None and 0.38 < res.diff < 0.42


def test_two_proportion_z_insufficient():
    res = two_proportion_z_test(up_a=5, n_a=10, up_b=40, n_b=100)
    assert res.insufficient is True
    assert res.p_value is None


def test_min_sample_is_30():
    assert MIN_SAMPLE == 30
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_stats.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.prompts'`

- [ ] **Step 3: 实现 `stats.py`**

```python
# app/prompts/stats.py
"""Significance tests implemented with the Python standard library only.

No numpy/scipy — t-distribution / normal tail probabilities use math.erf
and the regularized incomplete beta function (Numerical Recipes betai).
"""
import math
from dataclasses import dataclass
from statistics import mean, variance

MIN_SAMPLE = 30


@dataclass
class TTestResult:
    p_value: float | None
    diff: float | None
    ci95: tuple[float, float] | None
    insufficient: bool


@dataclass
class ZTestResult:
    p_value: float | None
    diff: float | None
    ci95: tuple[float, float] | None
    insufficient: bool


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes)."""
    MAXIT = 200
    EPS = 3.0e-12
    FPMIN = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_sf_two_sided(t: float, df: float) -> float:
    """Two-sided p-value for a t statistic with df degrees of freedom."""
    if df <= 0:
        return 1.0
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def _normal_two_sided(z: float) -> float:
    """Two-sided p-value for a standard normal statistic."""
    return math.erfc(abs(z) / math.sqrt(2.0))


# 95% two-sided critical value from the standard normal (used for CIs)
_Z_95 = 1.959963984540054


def welch_t_test(a: list[float], b: list[float]) -> TTestResult:
    """Welch's t-test. diff = mean(b) - mean(a). Two-sided."""
    n_a, n_b = len(a), len(b)
    if n_a < MIN_SAMPLE or n_b < MIN_SAMPLE:
        return TTestResult(p_value=None, diff=None, ci95=None, insufficient=True)
    mean_a, mean_b = mean(a), mean(b)
    var_a = variance(a) if n_a > 1 else 0.0
    var_b = variance(b) if n_b > 1 else 0.0
    diff = mean_b - mean_a
    se2 = var_a / n_a + var_b / n_b
    se = math.sqrt(se2)
    if se == 0.0:
        # No variance: significant iff means differ, but avoid div-by-zero.
        p = 0.0 if diff != 0.0 else 1.0
        return TTestResult(p_value=p, diff=diff, ci95=(diff, diff), insufficient=False)
    t = diff / se
    df = se2 * se2 / (
        (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    )
    p = _t_sf_two_sided(t, df)
    margin = _Z_95 * se
    return TTestResult(
        p_value=p, diff=diff, ci95=(diff - margin, diff + margin), insufficient=False
    )


def two_proportion_z_test(
    up_a: int, n_a: int, up_b: int, n_b: int
) -> ZTestResult:
    """Two-proportion z-test. diff = p_b - p_a. Two-sided."""
    if n_a < MIN_SAMPLE or n_b < MIN_SAMPLE:
        return ZTestResult(p_value=None, diff=None, ci95=None, insufficient=True)
    p_a = up_a / n_a
    p_b = up_b / n_b
    diff = p_b - p_a
    pooled = (up_a + up_b) / (n_a + n_b)
    se_pooled = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n_a + 1.0 / n_b))
    if se_pooled == 0.0:
        p = 0.0 if diff != 0.0 else 1.0
        return ZTestResult(p_value=p, diff=diff, ci95=(diff, diff), insufficient=False)
    z = diff / se_pooled
    p = _normal_two_sided(z)
    se_wald = math.sqrt(
        p_a * (1.0 - p_a) / n_a + p_b * (1.0 - p_b) / n_b
    )
    margin = _Z_95 * se_wald
    return ZTestResult(
        p_value=p, diff=diff, ci95=(diff - margin, diff + margin), insufficient=False
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_stats.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/prompts/stats.py apps/luna-corpus/tests/prompts/
git commit -m "feat(prompts): 纯标准库显著性检验 (Welch t / 双比例 z)"
```

---

### Task 2: Schemas 与文件默认模板

定义模块内外交互结构，以及文件保底模板。

**Files:**
- Create: `app/prompts/schemas.py`、`app/prompts/defaults.py`、`app/prompts/__init__.py`
- Test: `tests/prompts/test_defaults.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `app/prompts/schemas.py`：
    - `@dataclass ResolvedTemplate`：`version_id: str | None`、`prompt_key: str`、`lang: str`、`version_label: str`、`template_text: str`
    - `@dataclass Variant`：`version_id: str`、`weight: int`
  - `app/prompts/defaults.py`：
    - `RAG_QA_PROMPT_KEY = "rag_qa"`
    - `DEFAULT_TEMPLATES: dict[tuple[str, str], dict]`，键 `(prompt_key, lang)`，值含 `version_label`、`template_text`。模板正文含占位符 `{body}`。
    - `def render_rag_body(question, context, conversation_history="", conversation_summary=None) -> str`（复刻现有 prompt_builder 的 body 拼装逻辑）
    - `def default_version_id(prompt_key: str, lang: str) -> str`：返回稳定合成 ID，形如 `file::{prompt_key}::{lang}`

- [ ] **Step 1: 写失败测试**

```python
# tests/prompts/test_defaults.py
from app.prompts.defaults import (
    DEFAULT_TEMPLATES,
    RAG_QA_PROMPT_KEY,
    default_version_id,
    render_rag_body,
)


def test_default_templates_have_zh_and_en():
    assert (RAG_QA_PROMPT_KEY, "zh") in DEFAULT_TEMPLATES
    assert (RAG_QA_PROMPT_KEY, "en") in DEFAULT_TEMPLATES


def test_default_template_has_body_placeholder():
    tpl = DEFAULT_TEMPLATES[(RAG_QA_PROMPT_KEY, "zh")]["template_text"]
    assert "{body}" in tpl


def test_render_body_includes_all_sections():
    body = render_rag_body(
        question="Q?",
        context="CTX",
        conversation_history="HIST",
        conversation_summary="SUM",
    )
    assert "SUM" in body and "HIST" in body and "CTX" in body and "Q?" in body


def test_render_body_minimal_only_question():
    body = render_rag_body(question="Q?", context="")
    assert "Q?" in body
    assert "[Relevant Documents]" not in body


def test_default_version_id_stable():
    assert default_version_id("rag_qa", "zh") == "file::rag_qa::zh"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_defaults.py -v`
Expected: FAIL，`ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: 实现 schemas 与 defaults**

```python
# app/prompts/schemas.py
"""Structures shared across the prompts module."""
from dataclasses import dataclass


@dataclass
class ResolvedTemplate:
    """A concrete template chosen for one request."""

    version_id: str | None
    prompt_key: str
    lang: str
    version_label: str
    template_text: str


@dataclass
class Variant:
    """One arm of an A/B experiment."""

    version_id: str
    weight: int
```

```python
# app/prompts/defaults.py
"""File-backed default templates for the RAG Q&A prompt.

Plain-Python constants (not YAML) — the project keeps dependencies minimal
and has no yaml package. These are the fail-safe layer: always available
even when the DB has no rows.
"""

RAG_QA_PROMPT_KEY = "rag_qa"

_ZH_TEMPLATE = """你是一个基于文档的问答助手。请根据提供的上下文信息回答问题。

{body}

请基于上述信息给出回答。如果上下文中没有相关信息，请说明无法从提供的文档中找到答案。"""

_EN_TEMPLATE = """You are a document-based Q&A assistant. Please answer questions based on the provided context.

{body}

Please provide your answer based on the above information. If the relevant information is not found in the context, please indicate that you cannot find an answer from the provided documents."""

DEFAULT_TEMPLATES: dict[tuple[str, str], dict] = {
    (RAG_QA_PROMPT_KEY, "zh"): {
        "version_label": "file-default-zh",
        "template_text": _ZH_TEMPLATE,
    },
    (RAG_QA_PROMPT_KEY, "en"): {
        "version_label": "file-default-en",
        "template_text": _EN_TEMPLATE,
    },
}


def default_version_id(prompt_key: str, lang: str) -> str:
    """Synthetic stable id for a file-default version."""
    return f"file::{prompt_key}::{lang}"


def render_rag_body(
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Assemble the [sections] body shared by all rag_qa templates."""
    parts = []
    if conversation_summary:
        parts.append(f"[Prior Conversation Summary]\n{conversation_summary}\n")
    if conversation_history:
        parts.append(f"[Current Conversation]\n{conversation_history}\n")
    if context:
        parts.append(f"[Relevant Documents]\n{context}\n")
    parts.append(f"[Current Question]\n{question}")
    return "\n\n".join(parts)
```

```python
# app/prompts/__init__.py
"""Prompt & template governance (A/B experiments)."""
```

- [ ] **Step 4: 运行确认通过**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_defaults.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/prompts/schemas.py apps/luna-corpus/app/prompts/defaults.py apps/luna-corpus/app/prompts/__init__.py apps/luna-corpus/tests/prompts/test_defaults.py
git commit -m "feat(prompts): schemas 与文件默认模板 (rag_qa 中英文)"
```

---

### Task 3: 数据模型与迁移

新增 2 表 + 3 枚举，`QAInteraction` 加列，并写 Alembic 迁移。

**Files:**
- Modify: `app/db/models.py`（在 `QAReview` 相关定义之后追加；给 `QAInteraction` 加列）
- Create: `alembic/versions/20260713_0012_prompt_governance.py`
- Test: `tests/prompts/test_prompt_models.py`

**Interfaces:**
- Consumes: `Base`、`CHAR`、`String`、`Text`、`JSON`、`DateTime`、`Enum`、`func`、`uuid`（均已在 models.py 导入）
- Produces:
  - `class PromptStatus(str, enum.Enum)`：`DRAFT="draft"`、`ACTIVE="active"`、`ARCHIVED="archived"`
  - `class PromptSource(str, enum.Enum)`：`FILE="file"`、`DB="db"`
  - `class ExperimentStatus(str, enum.Enum)`：`RUNNING="running"`、`STOPPED="stopped"`
  - `class PromptVersion(Base)` → 表 `prompt_versions`，列：`id, prompt_key, version_label, lang, template_text, status, source, knowledge_base_id, created_at`
  - `class PromptExperiment(Base)` → 表 `prompt_experiments`，列：`id, knowledge_base_id, prompt_key, status, variants(JSON), created_at`
  - `QAInteraction.prompt_version_id: Mapped[str | None]`（`CHAR(36)`, nullable, index）

- [ ] **Step 1: 写失败测试**

```python
# tests/prompts/test_prompt_models.py
from app.db.database import Base
from app.db.models import (
    ExperimentStatus,
    PromptExperiment,
    PromptSource,
    PromptStatus,
    PromptVersion,
    QAInteraction,
)


def test_tables_registered():
    tables = Base.metadata.tables
    assert "prompt_versions" in tables
    assert "prompt_experiments" in tables


def test_qa_interaction_has_prompt_version_id():
    assert "prompt_version_id" in QAInteraction.__table__.columns


def test_prompt_version_columns():
    cols = PromptVersion.__table__.columns
    for name in (
        "id", "prompt_key", "version_label", "lang", "template_text",
        "status", "source", "knowledge_base_id", "created_at",
    ):
        assert name in cols


def test_prompt_experiment_columns():
    cols = PromptExperiment.__table__.columns
    for name in ("id", "knowledge_base_id", "prompt_key", "status", "variants", "created_at"):
        assert name in cols


def test_enum_values():
    assert PromptStatus.ACTIVE.value == "active"
    assert PromptSource.FILE.value == "file"
    assert ExperimentStatus.RUNNING.value == "running"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_prompt_models.py -v`
Expected: FAIL，`ImportError: cannot import name 'PromptVersion'`

- [ ] **Step 3: 修改 models.py**

在 `app/db/models.py` 中给 `QAInteraction` 追加一列（在 `created_at` 定义行之前插入）：

```python
    prompt_version_id: Mapped[str | None] = mapped_column(
        CHAR(36), nullable=True, index=True
    )
```

在文件末尾（`QAReview` 之后）追加：

```python
class PromptStatus(str, enum.Enum):
    """Lifecycle of a prompt version."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class PromptSource(str, enum.Enum):
    """Origin of a prompt version."""

    FILE = "file"
    DB = "db"


class ExperimentStatus(str, enum.Enum):
    """Lifecycle of a prompt A/B experiment."""

    RUNNING = "running"
    STOPPED = "stopped"


class PromptVersion(Base):
    """A managed, versioned prompt template asset."""

    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    prompt_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(100), nullable=False)
    lang: Mapped[str] = mapped_column(String(10), nullable=False)
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PromptStatus] = mapped_column(
        Enum(PromptStatus), nullable=False, default=PromptStatus.DRAFT
    )
    source: Mapped[PromptSource] = mapped_column(
        Enum(PromptSource), nullable=False, default=PromptSource.DB
    )
    knowledge_base_id: Mapped[str | None] = mapped_column(
        CHAR(36), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PromptExperiment(Base):
    """Per-knowledge-base A/B experiment configuration."""

    __tablename__ = "prompt_experiments"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), nullable=False, index=True
    )
    prompt_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[ExperimentStatus] = mapped_column(
        Enum(ExperimentStatus), nullable=False, default=ExperimentStatus.RUNNING
    )
    variants: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

> 注：若 `Base` 从 `app.db.database` 导出而 models 内是 re-export，测试里 `from app.db.database import Base` 应可用；若不可用，改为 `from app.db.models import Base`。执行前用 `grep -n "^Base\|import Base\|Base =" app/db/database.py app/db/models.py` 确认。

- [ ] **Step 4: 运行确认通过**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_prompt_models.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 写迁移**

```python
# alembic/versions/20260713_0012_prompt_governance.py
"""prompt governance: prompt_versions, prompt_experiments, qa_interactions.prompt_version_id

Revision ID: 20260713_0012
Revises: 20260713_0011
Create Date: 2026-07-13

"""
import sqlalchemy as sa
from alembic import op

revision = "20260713_0012"
down_revision = "20260713_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("prompt_key", sa.String(length=50), nullable=False),
        sa.Column("version_label", sa.String(length=100), nullable=False),
        sa.Column("lang", sa.String(length=10), nullable=False),
        sa.Column("template_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("draft", "active", "archived", name="promptstatus"), nullable=False),
        sa.Column("source", sa.Enum("file", "db", name="promptsource"), nullable=False),
        sa.Column("knowledge_base_id", sa.CHAR(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_prompt_versions_prompt_key", "prompt_versions", ["prompt_key"])
    op.create_index("ix_prompt_versions_knowledge_base_id", "prompt_versions", ["knowledge_base_id"])

    op.create_table(
        "prompt_experiments",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("knowledge_base_id", sa.CHAR(36), nullable=False),
        sa.Column("prompt_key", sa.String(length=50), nullable=False),
        sa.Column("status", sa.Enum("running", "stopped", name="experimentstatus"), nullable=False),
        sa.Column("variants", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_prompt_experiments_knowledge_base_id", "prompt_experiments", ["knowledge_base_id"])
    op.create_index("ix_prompt_experiments_prompt_key", "prompt_experiments", ["prompt_key"])

    op.add_column(
        "qa_interactions",
        sa.Column("prompt_version_id", sa.CHAR(36), nullable=True),
    )
    op.create_index(
        "ix_qa_interactions_prompt_version_id", "qa_interactions", ["prompt_version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_qa_interactions_prompt_version_id", table_name="qa_interactions")
    op.drop_column("qa_interactions", "prompt_version_id")
    op.drop_index("ix_prompt_experiments_prompt_key", table_name="prompt_experiments")
    op.drop_index("ix_prompt_experiments_knowledge_base_id", table_name="prompt_experiments")
    op.drop_table("prompt_experiments")
    op.drop_index("ix_prompt_versions_knowledge_base_id", table_name="prompt_versions")
    op.drop_index("ix_prompt_versions_prompt_key", table_name="prompt_versions")
    op.drop_table("prompt_versions")
```

- [ ] **Step 6: 提交**

```bash
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/alembic/versions/20260713_0012_prompt_governance.py apps/luna-corpus/tests/prompts/test_prompt_models.py
git commit -m "feat(prompts): prompt_versions/prompt_experiments 表 + QAInteraction 版本列与迁移"
```

---

### Task 4: Registry（文件默认层 + DB 覆盖层 + 缓存）

**Files:**
- Create: `app/prompts/registry.py`
- Test: `tests/prompts/test_registry.py`

**Interfaces:**
- Consumes: `DEFAULT_TEMPLATES`、`default_version_id`、`RAG_QA_PROMPT_KEY`（defaults.py）；`ResolvedTemplate`（schemas.py）；`PromptVersion`、`PromptStatus`、`PromptSource`（models.py）
- Produces:
  - `def get_default_template(prompt_key: str, lang: str) -> ResolvedTemplate`（纯文件层，无 DB；未知 key/lang 回退到 `(prompt_key,"zh")`，再回退 rag_qa/zh）
  - `def get_template_by_version_id(db, version_id: str, prompt_key: str, lang: str) -> ResolvedTemplate`（version_id 以 `file::` 开头或 DB 查不到 → 文件默认；否则读 DB 行，带缓存）
  - `def invalidate(version_id: str) -> None`（清除单条缓存）
  - `def invalidate_all() -> None`（清空缓存，测试与写操作后用）

- [ ] **Step 1: 写失败测试**

```python
# tests/prompts/test_registry.py
import pytest

from app.db.models import PromptSource, PromptStatus, PromptVersion
from app.prompts import registry
from app.prompts.defaults import default_version_id


@pytest.fixture(autouse=True)
def _clear_cache():
    registry.invalidate_all()
    yield
    registry.invalidate_all()


def test_get_default_template_zh():
    t = registry.get_default_template("rag_qa", "zh")
    assert t.version_id == default_version_id("rag_qa", "zh")
    assert "{body}" in t.template_text
    assert t.lang == "zh"


def test_unknown_lang_falls_back_to_zh():
    t = registry.get_default_template("rag_qa", "fr")
    assert t.lang == "zh"


def test_file_version_id_returns_default(db_session):
    t = registry.get_template_by_version_id(
        db_session, default_version_id("rag_qa", "en"), "rag_qa", "en"
    )
    assert t.lang == "en"
    assert "{body}" in t.template_text


def test_db_version_id_reads_row(db_session):
    row = PromptVersion(
        prompt_key="rag_qa",
        version_label="v2-concise",
        lang="zh",
        template_text="自定义 {body} 模板",
        status=PromptStatus.ACTIVE,
        source=PromptSource.DB,
    )
    db_session.add(row)
    db_session.commit()
    t = registry.get_template_by_version_id(db_session, row.id, "rag_qa", "zh")
    assert t.version_id == row.id
    assert t.version_label == "v2-concise"
    assert "自定义" in t.template_text


def test_missing_db_row_falls_back_to_default(db_session):
    t = registry.get_template_by_version_id(
        db_session, "00000000-0000-0000-0000-000000000000", "rag_qa", "zh"
    )
    assert t.version_id == default_version_id("rag_qa", "zh")
```

> `db_session` fixture：先 `grep -rn "def db_session\|@pytest.fixture" tests/conftest.py tests/**/conftest.py` 确认名称；若现有 fixture 名不同（如 `db`），改用现有名。

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_registry.py -v`
Expected: FAIL，`AttributeError: module 'app.prompts.registry' has no attribute ...`

- [ ] **Step 3: 实现 registry.py**

```python
# app/prompts/registry.py
"""Template loading: file-default layer + DB-override layer + in-memory cache."""
from sqlalchemy.orm import Session

from app.db.models import PromptVersion
from app.observability.logging import get_logger
from app.prompts.defaults import (
    DEFAULT_TEMPLATES,
    RAG_QA_PROMPT_KEY,
    default_version_id,
)
from app.prompts.schemas import ResolvedTemplate

logger = get_logger("luna.prompts.registry")

# version_id -> ResolvedTemplate (DB rows only; file defaults are cheap to rebuild)
_CACHE: dict[str, ResolvedTemplate] = {}


def get_default_template(prompt_key: str, lang: str) -> ResolvedTemplate:
    """File-default layer. Never touches the DB. Always returns something."""
    entry = DEFAULT_TEMPLATES.get((prompt_key, lang))
    resolved_lang = lang
    if entry is None:
        entry = DEFAULT_TEMPLATES.get((prompt_key, "zh"))
        resolved_lang = "zh"
    if entry is None:
        entry = DEFAULT_TEMPLATES[(RAG_QA_PROMPT_KEY, "zh")]
        prompt_key, resolved_lang = RAG_QA_PROMPT_KEY, "zh"
    return ResolvedTemplate(
        version_id=default_version_id(prompt_key, resolved_lang),
        prompt_key=prompt_key,
        lang=resolved_lang,
        version_label=entry["version_label"],
        template_text=entry["template_text"],
    )


def get_template_by_version_id(
    db: Session, version_id: str, prompt_key: str, lang: str
) -> ResolvedTemplate:
    """Resolve a template by version id, falling back to the file default."""
    if not version_id or version_id.startswith("file::"):
        return get_default_template(prompt_key, lang)
    cached = _CACHE.get(version_id)
    if cached is not None:
        return cached
    try:
        row = db.query(PromptVersion).filter(PromptVersion.id == version_id).first()
    except Exception:
        logger.warning("prompt_version_load_failed", version_id=version_id, exc_info=True)
        return get_default_template(prompt_key, lang)
    if row is None:
        return get_default_template(prompt_key, lang)
    resolved = ResolvedTemplate(
        version_id=row.id,
        prompt_key=row.prompt_key,
        lang=row.lang,
        version_label=row.version_label,
        template_text=row.template_text,
    )
    _CACHE[version_id] = resolved
    return resolved


def invalidate(version_id: str) -> None:
    _CACHE.pop(version_id, None)


def invalidate_all() -> None:
    _CACHE.clear()
```

- [ ] **Step 4: 运行确认通过**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_registry.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/prompts/registry.py apps/luna-corpus/tests/prompts/test_registry.py
git commit -m "feat(prompts): registry 文件默认层+DB覆盖层+缓存"
```

---

### Task 5: Experiment（稳定哈希分流 + select_version）

**Files:**
- Create: `app/prompts/experiment.py`
- Test: `tests/prompts/test_experiment.py`

**Interfaces:**
- Consumes: `PromptExperiment`、`ExperimentStatus`（models.py）；`registry.get_template_by_version_id`、`get_default_template`；`ResolvedTemplate`、`Variant`
- Produces:
  - `def stable_bucket(seed: str, prompt_key: str) -> int`：返回 0..99
  - `def pick_version_id(variants: list[dict], bucket: int) -> str | None`：按 weight 累加区间选中 version_id；variants 为空或权重和为 0 → None
  - `def select_version(db, knowledge_base_id, prompt_key, lang, seed) -> ResolvedTemplate`：查 running 实验 → 分流；无实验/异常 → 文件默认。**永不抛异常。**

- [ ] **Step 1: 写失败测试**

```python
# tests/prompts/test_experiment.py
import pytest

from app.db.models import (
    ExperimentStatus,
    PromptExperiment,
    PromptSource,
    PromptStatus,
    PromptVersion,
)
from app.prompts import experiment, registry
from app.prompts.defaults import default_version_id


@pytest.fixture(autouse=True)
def _clear_cache():
    registry.invalidate_all()
    yield
    registry.invalidate_all()


def test_stable_bucket_is_deterministic():
    b1 = experiment.stable_bucket("conv-123", "rag_qa")
    b2 = experiment.stable_bucket("conv-123", "rag_qa")
    assert b1 == b2
    assert 0 <= b1 < 100


def test_stable_bucket_varies_by_seed():
    buckets = {experiment.stable_bucket(f"conv-{i}", "rag_qa") for i in range(50)}
    assert len(buckets) > 1  # not all identical


def test_pick_version_boundaries():
    variants = [{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}]
    assert experiment.pick_version_id(variants, 0) == "A"
    assert experiment.pick_version_id(variants, 49) == "A"
    assert experiment.pick_version_id(variants, 50) == "B"
    assert experiment.pick_version_id(variants, 99) == "B"


def test_pick_version_empty_returns_none():
    assert experiment.pick_version_id([], 10) is None
    assert experiment.pick_version_id([{"version_id": "A", "weight": 0}], 10) is None


def test_select_version_no_experiment_returns_default(db_session):
    t = experiment.select_version(db_session, "kb-1", "rag_qa", "zh", seed="s1")
    assert t.version_id == default_version_id("rag_qa", "zh")


def test_select_version_running_experiment_picks_variant(db_session):
    row = PromptVersion(
        prompt_key="rag_qa", version_label="v2", lang="zh",
        template_text="变体 {body}", status=PromptStatus.ACTIVE, source=PromptSource.DB,
    )
    db_session.add(row)
    db_session.commit()
    exp = PromptExperiment(
        knowledge_base_id="kb-1", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": row.id, "weight": 100}],
    )
    db_session.add(exp)
    db_session.commit()
    t = experiment.select_version(db_session, "kb-1", "rag_qa", "zh", seed="s1")
    assert t.version_id == row.id


def test_select_version_stopped_experiment_ignored(db_session):
    exp = PromptExperiment(
        knowledge_base_id="kb-9", prompt_key="rag_qa",
        status=ExperimentStatus.STOPPED,
        variants=[{"version_id": "whatever", "weight": 100}],
    )
    db_session.add(exp)
    db_session.commit()
    t = experiment.select_version(db_session, "kb-9", "rag_qa", "zh", seed="s1")
    assert t.version_id == default_version_id("rag_qa", "zh")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_experiment.py -v`
Expected: FAIL，`AttributeError` / `ImportError`

- [ ] **Step 3: 实现 experiment.py**

```python
# app/prompts/experiment.py
"""Per-KB experiment lookup + stable-hash traffic split. Never raises."""
import hashlib

from sqlalchemy.orm import Session

from app.db.models import ExperimentStatus, PromptExperiment
from app.observability.logging import get_logger
from app.prompts import registry
from app.prompts.schemas import ResolvedTemplate

logger = get_logger("luna.prompts.experiment")


def stable_bucket(seed: str, prompt_key: str) -> int:
    """Reproducible 0..99 bucket from a seed + prompt key."""
    digest = hashlib.sha256(f"{seed}:{prompt_key}".encode()).hexdigest()
    return int(digest, 16) % 100


def pick_version_id(variants: list[dict], bucket: int) -> str | None:
    """Map a bucket into a variant by cumulative weight."""
    total = sum(int(v.get("weight", 0)) for v in variants)
    if total <= 0:
        return None
    # scale bucket (0..99) onto 0..total
    threshold = bucket * total / 100.0
    cumulative = 0.0
    for v in variants:
        cumulative += int(v.get("weight", 0))
        if threshold < cumulative:
            return v.get("version_id")
    return variants[-1].get("version_id")


def select_version(
    db: Session,
    knowledge_base_id: str,
    prompt_key: str,
    lang: str,
    seed: str,
) -> ResolvedTemplate:
    """Choose the template for this request. Falls back to file default on
    any missing experiment or error."""
    try:
        exp = (
            db.query(PromptExperiment)
            .filter(
                PromptExperiment.knowledge_base_id == knowledge_base_id,
                PromptExperiment.prompt_key == prompt_key,
                PromptExperiment.status == ExperimentStatus.RUNNING,
            )
            .first()
        )
        if exp is None or not exp.variants:
            return registry.get_default_template(prompt_key, lang)
        bucket = stable_bucket(seed, prompt_key)
        version_id = pick_version_id(exp.variants, bucket)
        if not version_id:
            return registry.get_default_template(prompt_key, lang)
        return registry.get_template_by_version_id(db, version_id, prompt_key, lang)
    except Exception:
        logger.warning(
            "select_version_failed",
            knowledge_base_id=knowledge_base_id,
            prompt_key=prompt_key,
            exc_info=True,
        )
        return registry.get_default_template(prompt_key, lang)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_experiment.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/prompts/experiment.py apps/luna-corpus/tests/prompts/test_experiment.py
git commit -m "feat(prompts): 稳定哈希分流与 select_version（fail-safe）"
```

---

### Task 6: prompt_builder 解耦 + 图链路回填 version_id

把 `prompt_builder` 改为渲染器，在 `generate_node` 里选版本并把 `prompt_version_id` 经 result 带回到 `record_interaction`。

**Files:**
- Modify: `app/services/prompt_builder.py`、`app/graph/state.py`、`app/graph/rag_graph.py`、`app/quality/recorder.py`、`app/api/routes.py`
- Test: `tests/prompts/test_prompt_builder.py`、扩展 `tests/quality/test_recorder.py`（新增一个用例）

**Interfaces:**
- Consumes: `render_rag_body`（defaults.py）；`select_version`（experiment.py）；`ResolvedTemplate`
- Produces:
  - `prompt_builder.render_prompt(template_text: str, question, context, conversation_history="", conversation_summary=None) -> str`（用 `render_rag_body` 生成 body，再 `template_text.replace("{body}", body)`）
  - 保留 `build_rag_prompt` / `build_rag_prompt_en` 作为薄封装（向后兼容：内部取文件默认模板 + render_prompt），避免破坏其他调用方
  - `recorder.record_interaction(...)` 新增关键字参数 `prompt_version_id: str | None = None`，写入 `QAInteraction.prompt_version_id`
  - `RAGState` 新增键 `prompt_version_id: str | None`
  - `answer_question` / `answer_question_multi_turn` 的返回 dict 新增 `"prompt_version_id"`

- [ ] **Step 1: 写失败测试**

```python
# tests/prompts/test_prompt_builder.py
from app.services.prompt_builder import build_rag_prompt, render_prompt


def test_render_prompt_replaces_body():
    tpl = "PREFIX\n{body}\nSUFFIX"
    out = render_prompt(tpl, question="Q?", context="CTX")
    assert out.startswith("PREFIX")
    assert out.endswith("SUFFIX")
    assert "Q?" in out and "CTX" in out


def test_build_rag_prompt_backward_compatible():
    # 旧签名仍可用，输出含中文默认外壳
    out = build_rag_prompt(question="Q?", context="CTX")
    assert "基于文档的问答助手" in out
    assert "Q?" in out
```

追加到 `tests/quality/test_recorder.py`：

```python
def test_record_interaction_persists_prompt_version_id(db_session):
    from app.db.models import QAInteraction
    from app.quality.recorder import record_interaction

    iid = record_interaction(
        db_session,
        knowledge_base_id="kb-1",
        question="q",
        answer="a",
        sources=[],
        prompt_version_id="ver-123",
    )
    assert iid is not None
    row = db_session.query(QAInteraction).filter(QAInteraction.id == iid).first()
    assert row.prompt_version_id == "ver-123"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_prompt_builder.py tests/quality/test_recorder.py::test_record_interaction_persists_prompt_version_id -v`
Expected: FAIL，`ImportError: cannot import name 'render_prompt'` 及 `TypeError: unexpected keyword 'prompt_version_id'`

- [ ] **Step 3a: 改 prompt_builder.py**

将文件替换为：

```python
"""Prompt rendering. Template selection lives in app.prompts.experiment."""
from app.prompts.defaults import RAG_QA_PROMPT_KEY, render_rag_body
from app.prompts.registry import get_default_template


def render_prompt(
    template_text: str,
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Fill a template's {body} placeholder with the assembled sections."""
    body = render_rag_body(
        question=question,
        context=context,
        conversation_history=conversation_history,
        conversation_summary=conversation_summary,
    )
    return template_text.replace("{body}", body)


def build_rag_prompt(
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Backward-compatible helper: render with the zh file-default template."""
    tpl = get_default_template(RAG_QA_PROMPT_KEY, "zh")
    return render_prompt(
        tpl.template_text, question, context, conversation_history, conversation_summary
    )


def build_rag_prompt_en(
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Backward-compatible helper: render with the en file-default template."""
    tpl = get_default_template(RAG_QA_PROMPT_KEY, "en")
    return render_prompt(
        tpl.template_text, question, context, conversation_history, conversation_summary
    )
```

- [ ] **Step 3b: 改 recorder.py**

给 `record_interaction` 签名加参数（在 `conversation_id` 后）：

```python
    conversation_id: str | None = None,
    prompt_version_id: str | None = None,
) -> str | None:
```

在构造 `QAInteraction(...)` 时加字段：

```python
            retrieval_mode=retrieval_mode,
            processing_time_ms=processing_time_ms,
            prompt_version_id=prompt_version_id,
```

- [ ] **Step 3c: 改 state.py**

在 `RAGState` 末尾加键：

```python
    prompt_version_id: str | None
```

- [ ] **Step 3d: 改 rag_graph.py 的 `generate_node`**

在文件顶部导入处，把
`from app.services.prompt_builder import build_rag_prompt`
改为：
```python
from app.services.prompt_builder import build_rag_prompt, render_prompt
from app.prompts.experiment import select_version
from app.prompts.defaults import RAG_QA_PROMPT_KEY
from app.db.database import SessionLocal
```
（`SessionLocal` 已在该文件导入，勿重复。）

在 `generate_node` 中，把（约 235 行）：
```python
    # Build complete prompt with conversation context
    full_prompt = build_rag_prompt(
        question=question,
        context=context,
        conversation_history=conversation_history,
        conversation_summary=conversation_summary,
    )
```
替换为：
```python
    # Select prompt version (A/B), then render. Fail-safe to file default.
    knowledge_base_id = state.get("knowledge_base_id")
    conversation_id = state.get("conversation_id")
    seed = conversation_id or knowledge_base_id or "default"
    db = SessionLocal()
    try:
        resolved = select_version(
            db, knowledge_base_id, RAG_QA_PROMPT_KEY, "zh", seed=seed
        )
    finally:
        db.close()
    full_prompt = render_prompt(
        resolved.template_text,
        question=question,
        context=context,
        conversation_history=conversation_history,
        conversation_summary=conversation_summary,
    )
    prompt_version_id = resolved.version_id
```

并把 `generate_node` 的 return（约 250 行）：
```python
    return {"answer": answer, "sources": sources}
```
改为：
```python
    return {"answer": answer, "sources": sources, "prompt_version_id": prompt_version_id}
```

> 注：`generate_node` 内已有 `conversation_id = state.get("conversation_id")`（约 203 行）。若重复定义会 shadow，删除新加的重复行，仅保留一处。执行前 `grep -n "conversation_id = state.get" app/graph/rag_graph.py` 核对。

- [ ] **Step 3e: 改 `answer_question` 与 `answer_question_multi_turn` 的返回 dict**

`answer_question`（约 321 行）return 中追加：
```python
        "retrieval_mode": settings.retrieval_mode.value,
        "prompt_version_id": result.get("prompt_version_id"),
    }
```
`answer_question_multi_turn`（约 462 行）return 中追加同一行 `"prompt_version_id": result.get("prompt_version_id"),`。

- [ ] **Step 3f: 改 routes.py 两处 `record_interaction` 调用**

两处（约 492、1443 行）均在末尾追加：
```python
        prompt_version_id=result.get("prompt_version_id"),
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_prompt_builder.py tests/quality/test_recorder.py -v`
Expected: PASS

- [ ] **Step 5: 回归运行图与质量相关测试**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/quality tests/graph -v`
Expected: PASS（确认解耦未破坏既有行为）

- [ ] **Step 6: 提交**

```bash
git add apps/luna-corpus/app/services/prompt_builder.py apps/luna-corpus/app/graph/state.py apps/luna-corpus/app/graph/rag_graph.py apps/luna-corpus/app/quality/recorder.py apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/prompts/test_prompt_builder.py apps/luna-corpus/tests/quality/test_recorder.py
git commit -m "feat(prompts): prompt_builder 渲染解耦 + 图链路回填 prompt_version_id"
```

---

### Task 7: 报告服务（按版本聚合 + 显著性对比）

**Files:**
- Create: `app/prompts/report.py`
- Test: `tests/prompts/test_report.py`

**Interfaces:**
- Consumes: `QAInteraction`、`QAEvaluation`、`QAFeedback`、`FeedbackRating`、`EvaluationStatus`、`PromptExperiment`、`ExperimentStatus`（models）；`welch_t_test`、`two_proportion_z_test`（stats）
- Produces:
  - `def build_experiment_report(db, knowledge_base_id: str, prompt_key: str) -> dict`
    - 返回 `{"prompt_key", "variants": [...], "comparisons": [...]}`（结构见 spec 6.1）
    - 无 running 实验 → `{"prompt_key", "variants": [], "comparisons": []}`
    - baseline = variants 中第一个（配比列表首项）；其余逐一与 baseline 比
    - 连续指标：`faithfulness`、`answer_relevance`、`citation_accuracy` → Welch's t；`positive_rate` → 双比例 z
    - `verdict`：`p<0.05 且 diff>0` → `"variant significantly better"`；`p<0.05 且 diff<0` → `"variant significantly worse"`；`insufficient` → `"insufficient_sample"`；否则 `"no significant difference"`

- [ ] **Step 1: 写失败测试**

```python
# tests/prompts/test_report.py
import pytest

from app.db.models import (
    EvaluationStatus,
    ExperimentStatus,
    FeedbackRating,
    PromptExperiment,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
)
from app.prompts.report import build_experiment_report


def _seed_interactions(db, kb, version_id, n, faith, up_count):
    for i in range(n):
        it = QAInteraction(
            knowledge_base_id=kb, question="q", answer="a", sources=[],
            prompt_version_id=version_id,
        )
        db.add(it)
        db.flush()
        db.add(QAEvaluation(
            interaction_id=it.id, faithfulness=faith, answer_relevance=faith,
            citation_accuracy=faith, status=EvaluationStatus.COMPLETED,
        ))
        rating = FeedbackRating.UP if i < up_count else FeedbackRating.DOWN
        db.add(QAFeedback(interaction_id=it.id, rating=rating))
    db.commit()


def test_report_no_experiment_empty(db_session):
    rep = build_experiment_report(db_session, "kb-x", "rag_qa")
    assert rep["variants"] == []
    assert rep["comparisons"] == []


def test_report_two_variants_with_comparison(db_session):
    exp = PromptExperiment(
        knowledge_base_id="kb-1", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}],
    )
    db_session.add(exp)
    db_session.commit()
    _seed_interactions(db_session, "kb-1", "A", n=40, faith=0.5, up_count=12)
    _seed_interactions(db_session, "kb-1", "B", n=40, faith=0.8, up_count=32)

    rep = build_experiment_report(db_session, "kb-1", "rag_qa")
    labels = {v["version_id"] for v in rep["variants"]}
    assert labels == {"A", "B"}
    a = next(v for v in rep["variants"] if v["version_id"] == "A")
    assert a["n"] == 40
    faith_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "faithfulness"
    )
    assert faith_cmp["baseline"] == "A"
    assert faith_cmp["p_value"] < 0.05
    assert faith_cmp["verdict"] == "variant significantly better"


def test_report_small_sample_insufficient(db_session):
    exp = PromptExperiment(
        knowledge_base_id="kb-2", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}],
    )
    db_session.add(exp)
    db_session.commit()
    _seed_interactions(db_session, "kb-2", "A", n=5, faith=0.5, up_count=2)
    _seed_interactions(db_session, "kb-2", "B", n=5, faith=0.8, up_count=4)

    rep = build_experiment_report(db_session, "kb-2", "rag_qa")
    faith_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "faithfulness"
    )
    assert faith_cmp["verdict"] == "insufficient_sample"
    assert faith_cmp["p_value"] is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_report.py -v`
Expected: FAIL，`ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: 实现 report.py**

```python
# app/prompts/report.py
"""Per-version aggregation + significance comparison for prompt experiments."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    EvaluationStatus,
    ExperimentStatus,
    FeedbackRating,
    PromptExperiment,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
)
from app.prompts.stats import two_proportion_z_test, welch_t_test

_CONTINUOUS = ("faithfulness", "answer_relevance", "citation_accuracy")


def _scores(db: Session, kb: str, version_id: str, column) -> list[float]:
    rows = (
        db.query(column)
        .join(QAInteraction, QAEvaluation.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == kb,
            QAInteraction.prompt_version_id == version_id,
            QAEvaluation.status == EvaluationStatus.COMPLETED,
            column.isnot(None),
        )
        .all()
    )
    return [float(r[0]) for r in rows]


def _feedback_counts(db: Session, kb: str, version_id: str) -> tuple[int, int]:
    q = (
        db.query(QAFeedback)
        .join(QAInteraction, QAFeedback.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == kb,
            QAInteraction.prompt_version_id == version_id,
        )
    )
    total = q.count()
    up = q.filter(QAFeedback.rating == FeedbackRating.UP).count()
    return up, total


def _n(db: Session, kb: str, version_id: str) -> int:
    return (
        db.query(func.count(QAInteraction.id))
        .filter(
            QAInteraction.knowledge_base_id == kb,
            QAInteraction.prompt_version_id == version_id,
        )
        .scalar()
    ) or 0


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _verdict(p_value, diff, insufficient) -> str:
    if insufficient:
        return "insufficient_sample"
    if p_value is not None and p_value < 0.05:
        return (
            "variant significantly better"
            if diff > 0
            else "variant significantly worse"
        )
    return "no significant difference"


def build_experiment_report(
    db: Session, knowledge_base_id: str, prompt_key: str
) -> dict:
    exp = (
        db.query(PromptExperiment)
        .filter(
            PromptExperiment.knowledge_base_id == knowledge_base_id,
            PromptExperiment.prompt_key == prompt_key,
            PromptExperiment.status == ExperimentStatus.RUNNING,
        )
        .first()
    )
    if exp is None or not exp.variants:
        return {"prompt_key": prompt_key, "variants": [], "comparisons": []}

    version_ids = [v["version_id"] for v in exp.variants]

    # per-variant aggregates
    agg: dict[str, dict] = {}
    variants_out = []
    for vid in version_ids:
        scores = {c: _scores(db, knowledge_base_id, vid, getattr(QAEvaluation, c)) for c in _CONTINUOUS}
        up, fb_total = _feedback_counts(db, knowledge_base_id, vid)
        agg[vid] = {"scores": scores, "up": up, "fb_total": fb_total}
        metrics = {c: {"mean": _mean(scores[c])} for c in _CONTINUOUS}
        metrics["positive_rate"] = {
            "rate": round(up / fb_total, 4) if fb_total else None
        }
        variants_out.append({"version_id": vid, "n": _n(db, knowledge_base_id, vid), "metrics": metrics})

    # comparisons: each variant vs baseline (first)
    baseline = version_ids[0]
    comparisons = []
    for vid in version_ids[1:]:
        for c in _CONTINUOUS:
            res = welch_t_test(agg[baseline]["scores"][c], agg[vid]["scores"][c])
            comparisons.append({
                "baseline": baseline, "variant": vid, "metric": c, "test": "welch_t",
                "p_value": res.p_value, "diff": res.diff, "ci95": list(res.ci95) if res.ci95 else None,
                "verdict": _verdict(res.p_value, res.diff, res.insufficient),
            })
        z = two_proportion_z_test(
            agg[baseline]["up"], agg[baseline]["fb_total"],
            agg[vid]["up"], agg[vid]["fb_total"],
        )
        comparisons.append({
            "baseline": baseline, "variant": vid, "metric": "positive_rate",
            "test": "two_proportion_z", "p_value": z.p_value, "diff": z.diff,
            "ci95": list(z.ci95) if z.ci95 else None,
            "verdict": _verdict(z.p_value, z.diff, z.insufficient),
        })

    return {"prompt_key": prompt_key, "variants": variants_out, "comparisons": comparisons}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/prompts/test_report.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/prompts/report.py apps/luna-corpus/tests/prompts/test_report.py
git commit -m "feat(prompts): 按版本聚合 + 显著性对比报告"
```

---

### Task 8: API 端点 + 权限 + 端到端

新增权限、写操作端点（建版本/建实验/改实验）与只读报告端点。

**Files:**
- Modify: `app/auth/permissions.py`、`app/api/routes.py`
- Test: `tests/api/test_prompt_experiment_api.py`

**Interfaces:**
- Consumes: `PromptVersion`、`PromptExperiment`、`PromptStatus`、`PromptSource`、`ExperimentStatus`；`build_experiment_report`；`registry.invalidate_all`；`require_permission`、`AuthenticatedRequestContext`、`get_db`（routes.py 已导入）
- Produces（挂在现有 `router`，前缀沿用 `/qa`）：
  - `PermissionSlug.PROMPT_MANAGE = "prompt:manage"`，授予 `WORKSPACE_ADMIN`、`KB_EDITOR`
  - `POST /qa/prompt-versions`（PROMPT_MANAGE）：body `{prompt_key, version_label, lang, template_text, status?}` → 建 DB 版本（source=db），返回 `{id, ...}`
  - `POST /qa/experiments`（PROMPT_MANAGE）：body `{prompt_key, variants:[{version_id,weight}]}` → 建 running 实验（kb 取 context），返回 `{id, ...}`
  - `PATCH /qa/experiments/{experiment_id}`（PROMPT_MANAGE）：body `{status?, variants?}` → 改；改后 `registry.invalidate_all()`
  - `GET /qa/experiments/{prompt_key}/report`（QA_QUERY，与 quality summary 一致）：调 `build_experiment_report`，返回报告 dict

- [ ] **Step 1: 加权限**

在 `PermissionSlug` 加：
```python
    PROMPT_MANAGE = "prompt:manage"
```
在 `DEFAULT_ROLE_PERMISSIONS` 的 `WORKSPACE_ADMIN` 与 `KB_EDITOR` 元组末尾各加：
```python
        PermissionSlug.PROMPT_MANAGE,
```

- [ ] **Step 2: 写失败测试**

```python
# tests/api/test_prompt_experiment_api.py
"""E2E: create version -> create experiment -> report. Uses existing api fixtures."""


def test_prompt_experiment_flow(client, admin_headers, knowledge_base_id):
    # 1. create a DB version
    r = client.post(
        "/qa/prompt-versions",
        headers=admin_headers,
        json={
            "prompt_key": "rag_qa", "version_label": "v2-concise",
            "lang": "zh", "template_text": "简洁版 {body}", "status": "active",
        },
    )
    assert r.status_code == 200, r.text
    version_id = r.json()["id"]

    # 2. create experiment: file-default vs new version
    r = client.post(
        "/qa/experiments",
        headers=admin_headers,
        json={
            "prompt_key": "rag_qa",
            "variants": [
                {"version_id": "file::rag_qa::zh", "weight": 50},
                {"version_id": version_id, "weight": 50},
            ],
        },
    )
    assert r.status_code == 200, r.text
    exp_id = r.json()["id"]

    # 3. report is reachable and well-formed (empty aggregates ok)
    r = client.get("/qa/experiments/rag_qa/report", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prompt_key"] == "rag_qa"
    assert {v["version_id"] for v in body["variants"]} == {
        "file::rag_qa::zh", version_id,
    }

    # 4. stop the experiment
    r = client.patch(
        f"/qa/experiments/{exp_id}", headers=admin_headers, json={"status": "stopped"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "stopped"
```

> fixtures `client` / `admin_headers` / `knowledge_base_id`：执行前 `grep -rn "def client\|def admin_headers\|def knowledge_base_id\|@pytest.fixture" tests/api/conftest.py tests/conftest.py` 确认实际名称与获取 kb 上下文的方式，按现有 API 测试（如 `tests/api/` 下既有文件）的写法对齐 header/鉴权。

- [ ] **Step 3: 运行确认失败**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/api/test_prompt_experiment_api.py -v`
Expected: FAIL，404（路由未定义）

- [ ] **Step 4: 加端点到 routes.py**

在 `routes.py` 顶部导入区补充：
```python
from app.db.models import (
    ExperimentStatus,
    PromptExperiment,
    PromptSource,
    PromptStatus,
    PromptVersion,
)
from app.prompts import registry
from app.prompts.report import build_experiment_report
from app.auth.permissions import PermissionSlug  # 若已导入则跳过
from pydantic import BaseModel  # 若已导入则跳过
```
（先 `grep -n "from app.db.models import\|from pydantic import\|PermissionSlug" app/api/routes.py` 核对，避免重复导入；models 的导入合并进现有那条多行 import。）

在文件靠近其他 Pydantic 模型处加请求模型：
```python
class PromptVersionCreate(BaseModel):
    prompt_key: str
    version_label: str
    lang: str
    template_text: str
    status: str = "active"


class ExperimentVariantIn(BaseModel):
    version_id: str
    weight: int


class ExperimentCreate(BaseModel):
    prompt_key: str
    variants: list[ExperimentVariantIn]


class ExperimentPatch(BaseModel):
    status: str | None = None
    variants: list[ExperimentVariantIn] | None = None
```

在文件末尾（其他 `@router` 端点旁）加：
```python
@router.post("/qa/prompt-versions")
async def create_prompt_version(
    payload: PromptVersionCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.PROMPT_MANAGE)),
    ],
) -> dict:
    """Create a DB-sourced prompt version."""
    row = PromptVersion(
        prompt_key=payload.prompt_key,
        version_label=payload.version_label,
        lang=payload.lang,
        template_text=payload.template_text,
        status=PromptStatus(payload.status),
        source=PromptSource.DB,
        knowledge_base_id=context.knowledge_base.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "prompt_key": row.prompt_key,
        "version_label": row.version_label,
        "lang": row.lang,
        "status": row.status.value,
    }


@router.post("/qa/experiments")
async def create_experiment(
    payload: ExperimentCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.PROMPT_MANAGE)),
    ],
) -> dict:
    """Create a running A/B experiment for the current knowledge base."""
    row = PromptExperiment(
        knowledge_base_id=context.knowledge_base.id,
        prompt_key=payload.prompt_key,
        status=ExperimentStatus.RUNNING,
        variants=[v.model_dump() for v in payload.variants],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    registry.invalidate_all()
    return {
        "id": row.id,
        "prompt_key": row.prompt_key,
        "status": row.status.value,
        "variants": row.variants,
    }


@router.patch("/qa/experiments/{experiment_id}")
async def update_experiment(
    experiment_id: str,
    payload: ExperimentPatch,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.PROMPT_MANAGE)),
    ],
) -> dict:
    """Update experiment status and/or variants."""
    row = (
        db.query(PromptExperiment)
        .filter(
            PromptExperiment.id == experiment_id,
            PromptExperiment.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if payload.status is not None:
        row.status = ExperimentStatus(payload.status)
    if payload.variants is not None:
        row.variants = [v.model_dump() for v in payload.variants]
    db.commit()
    db.refresh(row)
    registry.invalidate_all()
    return {"id": row.id, "status": row.status.value, "variants": row.variants}


@router.get("/qa/experiments/{prompt_key}/report")
async def experiment_report(
    prompt_key: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
) -> dict:
    """Per-version aggregation + significance comparison."""
    return build_experiment_report(db, context.knowledge_base.id, prompt_key)
```

> 注：`HTTPException` 应已在 routes.py 导入；若否，`grep -n "HTTPException" app/api/routes.py` 后补 `from fastapi import HTTPException`。路径用 `/qa/experiments/{prompt_key}/report`（对齐现有 `/qa/quality/summary` 前缀），与 spec 中 `/experiments/{kb_id}/...` 的差异在于 kb 从鉴权 context 取而非路径参数——这与现有 quality 端点一致，是有意的对齐。

- [ ] **Step 5: 运行确认通过**

Run: `cd apps/luna-corpus && .venv/bin/pytest tests/api/test_prompt_experiment_api.py -v`
Expected: PASS

- [ ] **Step 6: 全量回归**

Run: `cd apps/luna-corpus && .venv/bin/pytest -q`
Expected: 全绿（新旧用例均通过）

- [ ] **Step 7: 提交**

```bash
git add apps/luna-corpus/app/auth/permissions.py apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_prompt_experiment_api.py
git commit -m "feat(prompts): 实验管理与报告端点 + PROMPT_MANAGE 权限"
```

---

## 自查（Self-Review）

**1. Spec 覆盖：**
- 模块结构（spec 3）→ Task 1-7 建齐 `stats/defaults/schemas/registry/experiment/report`（`report.py` 替代 spec 中的 report 归属，职责一致）。✅
- 数据模型（spec 4）→ Task 3（2 表 + QAInteraction 加列 + 迁移 + 保底 file 版本用合成 `file::` id 表达）。✅
- 运行时数据流（spec 5）→ Task 6（select_version → render → 回填 → record_interaction）；稳定哈希 seed 优先 conversation_id → Task 5/6；fail-safe → Task 5。✅
- 读取链路（spec 6）→ Task 7 报告 + Task 8 端点（读用 QA_QUERY，写用 PROMPT_MANAGE）。✅
- 统计（spec 7）→ Task 1（Welch t + 双比例 z + n<30 门槛 + 0 方差不崩）。✅
- 错误处理（spec 8）→ Task 5 fail-safe、Task 8 写操作后 `invalidate_all`、report 空数据返回 null。✅
- 测试计划（spec 9）→ 各 Task 均 TDD；端到端在 Task 8。✅
- 迁移（spec 10）→ Task 3，惯例待手动跑。✅

**2. 占位符扫描：** 无 TBD/TODO；每个代码步骤含完整代码。✅

**3. 类型一致性：**
- `ResolvedTemplate.version_id` 全链路一致（registry/experiment/report 均用 `version_id`）。✅
- `select_version(db, knowledge_base_id, prompt_key, lang, seed)` 签名在 Task 5 定义、Task 6 调用一致。✅
- `record_interaction(..., prompt_version_id=None)` 在 Task 6 定义并在两处调用点一致传参。✅
- `build_experiment_report(db, knowledge_base_id, prompt_key)` Task 7 定义、Task 8 调用一致。✅

**已知偏离 spec 处（均有意，已在正文标注）：**
1. 文件默认模板用 Python 常量模块（`defaults.py`）而非 YAML —— 项目无 yaml 依赖且刻意精简。
2. 报告端点路径 `/qa/experiments/{prompt_key}/report`，kb 从鉴权 context 取而非路径参数 —— 对齐现有 `/qa/quality/summary`。
3. file 保底版本用合成 id `file::{key}::{lang}` 表达（而非真的把 file 模板写一行进表）—— 更简单、无需同步脚本，且 registry/experiment 已识别该前缀回退。因此 spec 10 的「首次同步脚本」不再需要，迁移仅建表 + 加列。

## 执行落地提示

各 Task 首个含 fixture 的测试步骤，均要求执行者先 `grep` 确认 `db_session`/`client`/`admin_headers`/`knowledge_base_id` 等 fixture 的实际名称（沿用 `tests/conftest.py` 与 `tests/quality`、`tests/api` 现有约定），再落笔。这是 plan 无法替执行者硬编码的唯一环境耦合点。
