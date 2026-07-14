# 真实登录认证（密码登录 + 自签发 JWT）设计

## 背景与目标

`apps/luna-corpus` 当前的身份来源是 `X-User-Id` 请求头：谁在 header 里写哪个用户 ID，系统就认为请求来自该用户。RBAC 权限体系（`app/api/auth.py` + `app/auth/permissions.py`，3 角色 / 16 权限）虽然完整，但它建立在这个**不可信的身份**之上——任何人伪造 header 即可冒充任意用户。这是《企业级 RAG 落地差距分析》中标注为“安全风险最高”的缺口，也是“最小企业可用版本”第 1 条的核心。

**本次目标**：用真实登录认证替换 `X-User-Id` 信任链。系统自管用户名/密码，登录后签发 JWT，所有受保护路由从校验过的 token 解析身份，彻底消灭 header 信任漏洞。

**方案基线（已确认）**：
- 自签发 JWT + 密码登录（不接外部 OIDC）。
- access token（短期，无状态）+ refresh token（长期，有状态可撤销）。
- bcrypt 密码哈希；不做公开注册，管理员创建用户 + seed 脚本建首个 admin。
- 彻底替换 `X-User-Id`，一次切干净，不保留双模式。

## 非目标（YAGNI）

以下不在本次范围：密码重置邮件流、多因素认证、OIDC/SSO 对接、密码复杂度策略、登录失败锁定、用户自助注册。均留待后续。

## 第 1 节：数据模型变更

### `User` 模型新增字段

- `hashed_password: Mapped[str | None]`（bcrypt 结果，`nullable=True`）。允许未来 OIDC 用户无本地密码；本地登录用户此字段非空。

### 新增 `RefreshToken` 表

```
refresh_tokens
  id            CHAR(36) PK  default uuid4
  user_id       CHAR(36) FK -> users.id (ondelete CASCADE)
  token_hash    String(64)   -- refresh token 明文的 SHA-256，不存明文
  expires_at    DateTime
  revoked_at    DateTime NULL -- 登出 / 轮换 / 踢下线时置位
  created_at    DateTime server_default now()
  索引: index(user_id), unique(token_hash)
```

### 状态分工（关键取舍）

- **access token 无状态**：纯 JWT 验签，不查库，15 分钟过期。降低单次泄露风险。
- **refresh token 有状态**：明文的 SHA-256 存入 `refresh_tokens`，7 天过期。`/auth/refresh` 校验“存在 + 未撤销 + 未过期”，`/auth/logout` 置 `revoked_at`。以一张表的成本，顺带获得“主动撤销 / 登出 / 踢下线”能力。

### 迁移

单个 Alembic 迁移：新增 `users.hashed_password` 列 + 创建 `refresh_tokens` 表。跟在最新迁移 `20260714_0013_cost_quota` 之后。

## 第 2 节：新增模块与端点

### `app/auth/` 新增文件（与现有 `permissions.py` 同目录）

- `password.py`：bcrypt 封装 `hash_password(raw)` / `verify_password(raw, hashed)`，基于 `passlib[bcrypt]`。
- `tokens.py`：JWT 与 refresh token 工具。`create_access_token(user_id)` / `decode_access_token(token)` / `create_refresh_token()`（返回明文 + hash）/ `hash_refresh_token(raw)`。密钥、过期时间从 `Settings` 读。
- `service.py`：认证业务逻辑。`authenticate(db, email, password)`、`issue_token_pair(db, user)`、`rotate_refresh_token(db, raw_refresh)`、`revoke_refresh_token(db, raw_refresh)`。

### `app/api/auth_routes.py`（挂到 `/api/v1/auth`）

| 端点 | 认证要求 | 作用 |
|------|---------|------|
| `POST /auth/login` | 无（邮箱 + 密码） | 校验密码，返回 `{access_token, refresh_token, token_type, expires_in}` |
| `POST /auth/refresh` | 带 refresh token | 校验并**轮换**（旧的撤销、发新的一对），返回新 token 对 |
| `POST /auth/logout` | 带 refresh token | 撤销该 refresh token |
| `GET /auth/me` | 带 access token | 返回当前用户信息 |

**Refresh token 轮换**：每次 refresh 作废旧 token、签发新的一对（rotation），防重放。

### 配置项（`Settings` 新增）

- `jwt_secret_key`：生产必填，开发有默认值；生产启动时校验非空（沿用现有 production 校验模式）。
- `jwt_algorithm = "HS256"`
- `access_token_expire_minutes = 15`
- `refresh_token_expire_days = 7`

### 依赖新增

`python-jose[cryptography]`（JWT）、`passlib[bcrypt]`（密码哈希）。

## 第 3 节：身份链路切换（消灭 X-User-Id 信任）

改造 `app/api/auth.py` 的身份来源。

**改造前**：`require_permission` → 读 `X-User-Id` header → 查 `User`。

**改造后**：`require_permission` → 读 `Authorization: Bearer <token>` → 验签 access token → 取 `user_id` → 查 `User`。

关键点：

- `get_authenticated_context` 的 `x_user_id` 参数替换为从 `Authorization` header 解析的 `token`。token 缺失 → 401；验签失败 / 过期 → 401。
- **资源上下文 header 完全保留**：`X-Tenant-Id` / `X-Workspace-Id` / `X-Knowledge-Base-Id` 不变，它们是路由参数性质，不是身份。
- **所有现有受保护路由零改动**：`require_permission(...)` 对外签名（返回 `AuthenticatedRequestContext`）不变，只换内部身份来源。`AuthenticatedRequestContext` 结构（user / membership / permissions）不变。
- **Agent 路由天然覆盖**：`agent_routes.py` 同样走 `require_permission`，自动切换到 token，无需单独处理。满足差距文档“Agent RAG tool 不能绕过 API 权限”的要求。

## 第 4 节：Bootstrap、错误处理与测试

### Bootstrap（破解“先有 admin 才能建人”循环）

- 新增 `scripts/seed_admin.py`：从环境变量 / 命令行读 email + password，创建首个 `User` + 绑定 `workspace_admin` 角色。这是**唯一**不经 API、直接写库的入口，专门用于灌第一个管理员。
- 之后建用户走 API：新增 `POST /api/v1/users`（受 `WORKSPACE_MANAGE` 保护），由 admin 创建其他用户并设初始密码。
- **顺手堵口**：给现有裸露的 `create_tenant` / `create_workspace` / `create_knowledge_base` 端点补上 `require_permission` 保护（当前无认证，任何人可裸建租户，属本次“消灭信任漏洞”应堵的口子）。

### 错误处理（统一，防信息泄露）

- 登录失败（邮箱不存在或密码错）→ 统一 `401 "Invalid credentials"`，不区分具体原因（防用户枚举）。
- access token 过期 / 无效 → `401`，前端据此触发 refresh。
- refresh token 无效 / 已撤销 / 过期 → `401`，前端据此触发重新登录。
- 用户 `is_active=False` → `403`。

### 测试策略

- **单元**：`password.py`（hash / verify）；`tokens.py`（签发 / 验签 / 过期 / 篡改）。
- **集成**：login 成功 / 失败；refresh 轮换；旧 refresh 失效；logout 后 refresh 被拒；`/auth/me`。
- **回归**：伪造 `Authorization` header 应返回 401（验证信任漏洞已堵）。
- **fixture 迁移**：新增统一 `auth_headers(user)` helper（直接签测试 token），现有所有 API 测试从“传 `X-User-Id`”改用它。这是本次改动量最大处，但均为机械替换。

## 影响文件清单

- `app/db/models.py`（User 加字段、RefreshToken 新表）
- `app/core/config.py`（JWT 配置项 + 生产校验）
- `app/api/auth.py`（身份来源切换）
- `app/auth/password.py`、`app/auth/tokens.py`、`app/auth/service.py`（新增）
- `app/api/auth_routes.py`（新增）
- `app/api/tenant_routes.py`（补 require_permission）
- `app/main.py`（挂 auth_router）
- `scripts/seed_admin.py`（新增）
- `alembic/versions/`（新迁移）
- `pyproject.toml`（新增依赖）
- `apps/luna-corpus/.env.example` / `README.md`（JWT 配置说明、seed 步骤）
- `tests/`（auth 相关新测试 + fixture 迁移）

## 验收标准

- 未带有效 token 的请求无法访问任何受保护接口（文档、会话、问答、索引、Agent、租户管理）。
- 伪造 `Authorization` header 返回 401。
- 登录 → 拿 token → 携带访问受保护接口成功；access token 过期后可用 refresh 换新；logout 后 refresh 失效。
- 首个 admin 可由 seed 脚本创建；其余用户由 admin 经 API 创建。
- 现有受保护路由行为不变（除身份来源），权限矩阵测试全绿。
