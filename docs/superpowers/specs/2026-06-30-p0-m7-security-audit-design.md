# P0-M7 安全防护与审计 设计文档

- **日期**: 2026-06-30
- **里程碑**: P0-M7
- **范围**: 审计日志(核心) + API 限流 + 上传校验加固
- **依赖**: P0-M3 用户身份与 RBAC(`require_permission` / `AuthenticatedRequestContext`)、P0-M5 文件摄取管线(`IngestionService`)、P0-M1 配置承载
- **明确不做(拆为后续子里程碑)**: Prompt Injection 检测、PII / 敏感字段脱敏、403 拒绝审计、magic-byte 内容嗅探、Redis 分布式限流

## 1. 目标

降低企业知识泄露、接口滥用和不可追责风险:

- 对受保护操作建立可查询、可追责的审计轨迹。
- 对所有 API 路由限流,防止滥用与 LLM 成本攻击。
- 加固文件上传校验,堵住 M5 现有校验的缺口。

## 2. 架构与模块布局

三个相互独立的关注点,在不同层接入:

```
app/security/
  __init__.py
  context.py        # 请求级 contextvars: request_id, client_ip
  middleware.py     # RequestContextMiddleware(request_id + IP)
                    # RateLimitMiddleware(按身份 + 按类别, 429)
                    # BodySizeLimitMiddleware(非上传 JSON, 413)
  rate_limiter.py   # 进程内固定窗口限流器
  audit.py          # AuditService.record(...) + AuditAction 枚举
app/db/models.py    # + AuditLog 模型
app/api/routes.py   # 处理器内显式调用 AuditService.record(...)
app/core/config.py  # + 限流 / 请求体 / 上传白名单配置
alembic/versions/   # + audit_logs 迁移
```

**分层原则**:

- **中间件层**处理横切的请求级关注点(ID/IP、限流、请求体大小),在处理器执行前完成。
- **审计日志**在处理器内显式记录 —— 此处才知道语义化的操作名与资源 ID。
- **上传加固**扩展 M5 的 `IngestionService`(增强而非重写),避免重复校验逻辑。

## 3. 审计日志

### 3.1 数据模型 `AuditLog`(新表 `audit_logs`,含 Alembic 迁移)

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str PK | uuid,沿用现有模型约定 |
| `actor_user_id` | str FK→users, nullable | 操作主体;系统/未认证场景可空 |
| `tenant_id` / `workspace_id` / `knowledge_base_id` | str, nullable | 来自 `AuthenticatedRequestContext` 的隔离作用域 |
| `action` | str(枚举支撑) | 如 `document.create` / `document.delete` / `document.index` / `qa.query` |
| `resource_type` | str | `document` / `conversation` / `task` 等 |
| `resource_id` | str, nullable | 受影响资源 ID |
| `result` | str(枚举) | `success` / `failure` |
| `detail` | str, nullable | 如 `"not found"`、错误摘要 |
| `request_id` | str, nullable | 来自请求上下文 |
| `client_ip` | str, nullable | 来自请求上下文 |
| `created_at` | datetime | 服务端默认值 |

### 3.2 `AuditService`

- `record(db, action, resource_type, resource_id, result, context, detail=None)` —— 用传入的 `AuthenticatedRequestContext` 与 contextvars(request_id / IP)构造一行记录。
- **成功路径**: 在处理器自身 `db.commit()` **之前**调用,使审计行与业务操作在**同一事务**中提交。业务回滚则成功审计行一并回滚,不会谎报成功。
- **失败路径**: `record_failure(...)` 通过 `SessionLocal()` 打开一个**独立短生命周期会话**写入失败行并独立提交,即便处理器主事务回滚也能留存。处理器在 `except` 分支调用。
- **健壮性**: `record_failure` 吞掉自身异常(记日志,不抛出),审计失败绝不影响主请求。

### 3.3 P0 审计的操作

- `document.create`
- `document.delete`
- `document.index`(后台索引任务,在完成/失败时记录)
- `qa.query`

403 拒绝审计不在本里程碑范围(已决定推迟,避免侵入 M3 鉴权依赖)。

## 4. 限流与请求体大小中间件

### 4.1 `rate_limiter.py` —— 进程内限流器

固定窗口计数,按身份键存于字典并按窗口重置。身份 = `X-User-Id`(存在时)否则客户端 IP。无新依赖,单进程状态。

- `RateLimiter.check(key, category) -> bool` —— 自增并与该类别上限比较。
- **按类别上限(从配置读取)**,默认值:
  - `default`: 120 req/min
  - `qa`(`/qa/*`): 30 req/min(LLM 成本)
  - `upload`(`/files/upload`、`/documents/*/process`): 10 req/min
- 类别由请求路径在中间件中解析。

### 4.2 `RateLimitMiddleware`

解析类别 → 调用限流器 → 超限返回 **429** 并带 `Retry-After` 头。排除路径:`/`、健康检查。

### 4.3 `BodySizeLimitMiddleware`

对非 multipart 请求,请求体超过 `max_json_body_size`(配置,默认 1MB)返回 **413**。上传路由(multipart)在此跳过 —— 其大小限制由 M5 的 `max_upload_size` 负责。

### 4.4 中间件顺序(由外到内)

`RequestContextMiddleware` → `BodySizeLimitMiddleware` → `RateLimitMiddleware` → CORS → 路由。

请求上下文最先,确保任何下游 429/413 也能拿到 request_id / IP 用于记录。

### 4.5 已知限制(记录为后续)

进程内计数为每副本独立;多实例正确性(Redis 限流器)推迟到 M8 / 扩容阶段。

## 5. 上传校验加固

扩展 M5 的 `IngestionService.ingest_file`(已有 size/mime/duplicate 校验),堵住三处缺口:

1. **实际字节大小强制**: 当前仅当 `file.size`(客户端 `Content-Length`)为真时校验。读取 `content` 后追加 `len(content) > max_upload_size` → 413,防御缺失/伪造的 `Content-Length`。
2. **空文件拒绝**: `len(content) == 0` → **422**(空文件),新增 `EmptyFileError`。
3. **显式类型白名单**: 仍以 parser registry 作为白名单事实来源(已覆盖 PDF/DOCX/MD/HTML),在配置中暴露受支持列表以提升可见性;除更清晰的错误外无行为变化。

上传处理器现有 415/413/409 映射保留;新增 422(空文件)。

## 6. 配置新增(`app/core/config.py`)

- `rate_limit_enabled: bool = True`
- `rate_limit_default_per_minute: int = 120`
- `rate_limit_qa_per_minute: int = 30`
- `rate_limit_upload_per_minute: int = 10`
- `max_json_body_size: int = 1048576`(1MB)
- (`max_upload_size` 已存在)

## 7. 错误处理

| 状态码 | 场景 |
| --- | --- |
| 429(+`Retry-After`) | 触发限流 |
| 413 | JSON 请求体超限 / 上传超限 |
| 415 | 不支持的文件类型 |
| 422 | 空文件 |
| 409 | 重复文件 |

审计失败绝不破坏请求 —— `record_failure` 吞掉自身错误(记日志,不抛出)。

## 8. 测试

- `test_rate_limiter` —— 单元: 窗口重置、按类别上限、键解析(user vs IP)。
- `test_rate_limit_middleware` —— 限内正常;超限 429 并带 `Retry-After`。
- `test_body_size_middleware` —— 超 `max_json_body_size` 返回 413;multipart 跳过。
- `test_upload_validation` —— 超大(413)、不支持类型(415)、空文件(422)、合法通过。
- `test_audit_service` —— 成功行与操作同事务提交;失败行在回滚后留存;关键字段齐备(actor、action、resource、result、request_id、ip)。
- `test_audit_integration` —— document create/delete/index/QA 各产生一条正确 action + result 的审计行。
- `test_request_context` —— request_id 生成 / 透传自请求头;IP 捕获。

## 9. 验收标准

- 超过请求频率限制返回 429。
- 超过大小限制或不支持类型的上传被拒绝;空文件被拒绝。
- 超过 `max_json_body_size` 的非上传请求返回 413。
- 文档创建、删除、索引、问答均有审计记录,且含主体、操作、资源、结果、时间、request_id/IP。
- 业务操作回滚时不会留下谎报成功的审计行;失败行在回滚后仍可查询。
