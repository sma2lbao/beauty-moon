# P0-M8 可观测性代码层 设计文档

- **日期**: 2026-07-01
- **里程碑**: P0-M8
- **范围**: 结构化日志(structlog) + Prometheus metrics + 健康检查分级
- **依赖**: P0-M7 请求上下文(`app/security/context.py` 的 request_id / client_ip contextvars、`RequestContextMiddleware`)、P0-M3 身份上下文(`AuthenticatedRequestContext`)、P0-M1 配置承载
- **明确不做(拆为后续子里程碑)**: Dockerfile / docker-compose、README 部署手册、备份恢复与索引重建文档、OpenTelemetry trace、Grafana dashboard 与告警体系

## 1. 目标

让企业试点环境可排障、可度量:

- 每个请求产生结构化日志,自动携带 request_id / user_id / tenant_id,便于线上排查检索慢、错、幻觉、无引用等问题。
- 暴露 Prometheus 可抓取的 metrics: HTTP 请求数 / 错误率 / 延迟,以及检索、embedding、LLM、索引任务的分阶段耗时。
- 健康检查按依赖组件(数据库、向量库、LLM provider)分级,可判定整体状态。

**背景订正**(相对甘特分析原文):

- request_id middleware 已在 P0-M7 落地(`RequestContextMiddleware` + `app/security/context.py`)。M8 不重建它,而是**消费**它,并扩展上下文携带 user_id / tenant_id。
- P0-M6 采用进程内 `BackgroundTasks`,不存在独立队列进程。因此健康检查**无 queue 组件**;分级组件为数据库、向量库、LLM provider。若将来引入 Redis/Celery,再按预留结构增加组件。

## 2. 架构与模块布局

新增 `app/observability/` 模块,布局对齐现有 `app/security/`:

```
app/observability/
  __init__.py
  logging.py      # structlog 配置 + contextvars processor(注入 request_id/user_id/tenant_id)
  metrics.py      # Prometheus 指标定义 + time_stage 计时 helper
  middleware.py   # MetricsMiddleware(HTTP 请求数/错误/延迟 + access log)
app/security/context.py             # 扩展: 增加 user_id/tenant_id contextvar
app/api/context.py                  # auth 依赖解析身份后回填 user_id/tenant_id 到上下文
app/api/routes.py                   # /metrics 端点; /health 分级增强
app/graph/rag_graph.py              # 检索 / LLM 生成阶段计时
app/services/llm.py                 # embedding 阶段计时
app/services/document_processor.py  # 索引任务计时
app/core/config.py                  # + log_level / log_format / metrics_enabled
app/main.py                         # 启动时初始化日志; 注册 MetricsMiddleware
```

**分层原则**(与 M7 一致):

- **中间件层**采集横切的 HTTP metrics(请求数、错误率、延迟),并在响应返回时发一条结构化 access log。
- **业务计时**在各服务内用 `time_stage()` context manager 显式埋点 —— 只有那里才知道语义化的阶段名。
- **日志**通过 structlog 的 contextvars processor 自动带上 request_id / user_id / tenant_id,业务代码无需每次手传。
- **观测绝不破坏主请求**: 埋点、日志、健康检查中的异常一律吞掉并降级。

## 3. 结构化日志 (structlog)

### 3.1 配置 (`logging.py`)

在 `create_app()` 启动时调用一次 `configure_logging()`:

- 输出 **JSON**(生产)或**彩色 console**(开发),由 `app_env` / `log_format` 决定。
- 日志级别来自配置 `log_level`(默认 `INFO`)。
- 一条 **contextvars processor** 从 `app/security/context.py` 读取 request_id / user_id / tenant_id,自动注入每条日志。
- 标准库 `logging` 桥接到 structlog,使 uvicorn / sqlalchemy 等第三方日志也走同一 JSON 管道。

### 3.2 上下文扩展 (`app/security/context.py`)

当前仅存 `request_id` / `client_ip`。M8 增加 `user_id` / `tenant_id` 两个 contextvar 及其 getter/setter。

- `RequestContextMiddleware` 在中间件早期执行,此时身份尚未解析,拿不到 user_id / tenant_id。
- 由 **auth 依赖**(`app/api/context.py` 解析 `AuthenticatedRequestContext` 时)回填 user_id / tenant_id 到上下文。后续日志自动携带。
- `reset_request_context()` 一并清理新增的两个 contextvar。

### 3.3 请求日志

`MetricsMiddleware`(见 §4)在请求结束时发一条结构化 access log,字段: `request_id`、`user_id`、`tenant_id`、`method`、`path`、`status`、`latency_ms`。满足验收标准"每个请求日志都包含 request_id、user_id、tenant_id、path、status、latency"。

### 3.4 已知限制(记录为后续)

在 auth 依赖执行**之前**的请求(如 401/403、未认证路径),access log 的 `user_id` / `tenant_id` 为 `null`。这符合实际 —— 未认证请求本就没有身份,可接受。

## 4. Metrics (prometheus-client)

### 4.1 指标定义 (`metrics.py`)

使用默认全局 registry。

**HTTP 层**(由 `MetricsMiddleware` 采集):

| 指标 | 类型 | label |
| --- | --- | --- |
| `http_requests_total` | Counter | `method`, `path_template`, `status` |
| `http_request_duration_seconds` | Histogram | `method`, `path_template` |

关键设计点: label 用 **`path_template` 而非原始 path**,避免 `/documents/{id}` 这类高基数路径把 label 打爆。用 Starlette `request.scope["route"].path` 取模板;匹配不到用 `"unmatched"`。

**业务阶段**(由服务内 `time_stage()` 埋点):

| 指标 | 类型 | label | 埋点位置 |
| --- | --- | --- | --- |
| `rag_retrieval_duration_seconds` | Histogram | — | `app/graph/rag_graph.py` 检索节点 |
| `llm_generation_duration_seconds` | Histogram | `provider` | `app/graph/rag_graph.py` 生成节点 |
| `embedding_duration_seconds` | Histogram | `provider` | `app/services/llm.py` embedding 调用 |
| `index_task_duration_seconds` | Histogram | `result`(success/failure) | `app/services/document_processor.py` 索引任务 |

### 4.2 计时 helper

```python
@contextmanager
def time_stage(histogram, **labels):
    ...  # finally 里 observe, 异常安全
```

`with time_stage(RAG_RETRIEVAL_DURATION): ...`,业务代码只加两行、无侵入。异常路径也会记录耗时(在 `finally` observe)。

### 4.3 `MetricsMiddleware`

- 计时整个请求,在响应返回时 observe duration 并对 `http_requests_total` 自增。
- 解析 `path_template`,记录 `status`。
- 请求结束发结构化 access log(§3.3)。
- `metrics_enabled=False` 时跳过采集。

### 4.4 `/metrics` 端点

- `GET /metrics` 返回 `prometheus_client.generate_latest()`,`Content-Type: text/plain; version=0.0.4`。
- 挂在 app 根(不带 `/api/v1` 前缀)。
- 加入 M7 限流 exempt 列表(`app/security/middleware.py` 的 `_RATE_LIMIT_EXEMPT`),避免抓取被限流。
- `metrics_enabled=False` 时返回 404。

## 5. 健康检查分级

### 5.1 响应结构(升级 `HealthResponse`)

```json
{
  "status": "ok | degraded",
  "components": {
    "database":     {"status": "up | down", "latency_ms": 3},
    "vectorstore":  {"status": "up | down", "latency_ms": 12},
    "llm_provider": {"status": "up | down | not_configured", "provider": "ark"}
  }
}
```

### 5.2 判定规则

- `database` / `vectorstore` 任一 `down` → 整体 `degraded`。
- `llm_provider` 只按**当前配置的** provider(`settings.llm_provider`)判定,不再把 ollama+ark 都硬查一遍。`not_configured` 不算 down。
- 每个依赖检查包在 try/except + 计时里,任何异常记为 `down` 而非抛错。

### 5.3 HTTP 状态码

保持 `200`(degraded 也返回 200,body 中体现),符合探针惯例 —— 存活即 200,细节看 body。

### 5.4 为什么不查队列

M6 用进程内 `BackgroundTasks`,无独立队列进程,故无 "queue" 组件。结构已预留,将来接入 Redis/Celery 再加组件即可。

## 6. 配置新增 (`app/core/config.py`)

- `log_level: str = "INFO"`
- `log_format: Literal["json", "console"]` —— 默认按 `app_env`: production→json,其余→console
- `metrics_enabled: bool = True`

## 7. 错误处理

观测绝不破坏主请求:

- `time_stage` 的 `finally` 只 observe 不抛。
- 健康检查依赖异常记为 `down`,不向上抛。
- 日志写入失败不影响响应。
- `metrics_enabled=False` 时 `/metrics` 返回 404,中间件跳过采集。

## 8. 测试

- `test_logging` —— JSON formatter 输出含 request_id/user_id/tenant_id;console 格式在 dev 生效;标准库桥接生效。
- `test_metrics` —— `time_stage` 正确 observe(含异常路径);`path_template` 高基数收敛为模板;开关关闭时跳过。
- `test_metrics_endpoint` —— `/metrics` 返回 Prometheus 文本格式且 content-type 正确;限流 exempt;开关关闭返回 404。
- `test_metrics_middleware` —— 请求计数与状态码 label 正确;access log 字段齐全。
- `test_health_check` —— 各组件 up/down/not_configured;某依赖 down → overall degraded;未配置 provider 不拉低健康度。

## 9. 验收标准

- 每个请求日志都包含 request_id、user_id、tenant_id、path、status、latency(未认证请求的 user_id/tenant_id 允许为 null)。
- `/metrics` 端点可被 Prometheus 抓取,含 HTTP 请求数/错误率/延迟及检索/embedding/LLM/索引任务分阶段耗时。
- `/health` 能区分数据库、向量库、LLM provider 的组件状态,并据此判定整体 ok/degraded。
- 观测层任何异常都不影响主请求成功返回。
