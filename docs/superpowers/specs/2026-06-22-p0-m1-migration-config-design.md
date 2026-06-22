# P0-M1 迁移与配置底座设计

## 背景

`apps/luna-corpus` 当前仍处于 RAG 原型阶段，数据库表结构由应用启动时的 `Base.metadata.create_all` 自动创建，CORS 允许所有来源，环境配置没有显式区分 development、test、production。P0-M1 的目标是先建立迁移和配置底座，为后续 P0-M2 租户/知识库模型、P0-M3 权限模型和 P0-M6 异步任务模型提供可审计、可回滚的 schema 变更路径。

本设计采用“最小可上线底座”方案：只覆盖 Alembic initial migration、环境分层、生产禁用自动建表、CORS 白名单和 Nx 迁移命令入口，不提前实现租户、认证、文件摄取、异步任务或 Docker/Compose。

## 目标

- 引入 Alembic 管理 `luna-corpus` 数据库 schema。
- 从当前 SQLAlchemy models 生成 initial migration，用于可重建环境。
- 通过 `APP_ENV` 区分 development、test、production。
- 通过 `AUTO_CREATE_TABLES` 控制开发便利建表，并禁止生产自动建表。
- 通过配置化 `CORS_ALLOW_ORIGINS` 替代硬编码 wildcard CORS。
- 增加 Nx target，让迁移命令可通过 workspace 标准入口执行。
- 更新 README 和 `.env.example`，说明迁移和生产配置约束。

## 非目标

- 不做已有生产数据库 baseline/stamp；当前按可重建环境处理。
- 不新增 Tenant、Workspace、KnowledgeBase、User、Membership 等业务模型。
- 不实现 RBAC、JWT/OIDC、文件上传、异步索引任务、Docker/Compose。
- 不替换当前 MySQL 驱动和 SQLAlchemy 模型组织方式。

## 架构

P0-M1 由四个小边界组成：

1. **迁移边界**：Alembic 读取应用的 SQLAlchemy metadata 和 `Settings.database_url`，负责 schema 创建和后续变更。
2. **配置边界**：`Settings` 增加运行环境、自动建表和 CORS 配置，集中校验生产危险配置。
3. **启动边界**：FastAPI lifespan 不再无条件初始化数据库，而是根据配置决定是否调用 `init_db()`。
4. **命令边界**：Nx project targets 暴露迁移命令，避免直接依赖全局 CLI 或手写路径。

## 组件设计

### Alembic 迁移体系

新增：

- `apps/luna-corpus/alembic.ini`
- `apps/luna-corpus/alembic/env.py`
- `apps/luna-corpus/alembic/versions/<revision>_initial_schema.py`

`env.py` 需要：

- 将 `apps/luna-corpus` 加入 import path。
- 导入 `app.db.models.Base` 作为 `target_metadata`。
- 从 `app.core.config.get_settings().database_url` 获取连接 URL。
- 支持 offline 和 online migration。

initial migration 应创建当前模型对应表：

- `documents`
- `chunks`
- `conversations`
- `messages`

枚举字段沿用当前 SQLAlchemy 模型定义。外键、主键、nullable、默认值应与当前模型保持一致。

### Settings 配置

`apps/luna-corpus/app/core/config.py` 增加：

- `app_env: Literal["development", "test", "production"]` 或等价 Enum。
- `auto_create_tables: bool`，默认 `False`，本地如需便利建表由 `.env` 显式开启。
- `cors_allow_origins: list[str]` 或字符串解析后的 list。

配置校验规则：

- `APP_ENV=production` 且 `AUTO_CREATE_TABLES=true` 必须报错。
- `APP_ENV=production` 时 `CORS_ALLOW_ORIGINS` 不能为空，且不能包含 `*`。
- development/test 可以使用本地来源或空列表；不再在代码中硬编码 `allow_origins=["*"]`。

### 数据库初始化

`apps/luna-corpus/app/db/database.py` 保留 `init_db()`，但它变成开发便利能力，不再是生产路径。

`apps/luna-corpus/app/main.py` 的 lifespan 调整为：

- 读取 settings。
- 仅当 `settings.auto_create_tables` 为 true 时调用 `init_db()`。
- production 下危险组合由 Settings 校验提前阻止。

### CORS 配置

`apps/luna-corpus/app/main.py` 的 `CORSMiddleware` 使用 `settings.cors_allow_origins`。

CORS 配置来自环境变量，例如：

```env
CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:4200
```

解析后传入 FastAPI：

```python
allow_origins=settings.cors_allow_origins
```

### Nx targets

`apps/luna-corpus/project.json` 增加：

- `db-migrate`：在 `apps/luna-corpus` 工作目录执行 `uv run alembic -c alembic.ini upgrade head`。
- `db-revision`：在 `apps/luna-corpus` 工作目录执行 `uv run alembic -c alembic.ini revision --autogenerate`，后续可通过 Nx args 传入 message。

项目使用时应通过：

```bash
pnpm nx run luna-corpus:db-migrate
pnpm nx run luna-corpus:db-revision --args="-m add_new_model"
```

具体 flags 实现前需用 Nx target 帮助或现有 run-commands 行为确认，不猜测不确定 CLI flags。

### 文档

更新：

- `apps/luna-corpus/.env.example`
- `apps/luna-corpus/README.md`

README 至少包含：

- 依赖服务：MySQL、Chroma、LLM provider。
- 环境变量说明。
- 数据库迁移命令。
- 本地启动命令。
- 生产环境必须关闭自动建表。
- CORS 白名单配置示例。

## 数据流

### 本地开发

1. 开发者复制 `.env.example` 到 `.env`。
2. 配置 `DATABASE_URL`、`APP_ENV=development`、`CORS_ALLOW_ORIGINS`。
3. 执行 `pnpm nx run luna-corpus:db-migrate` 创建表结构。
4. 执行 `pnpm nx run luna-corpus:serve` 启动 API。
5. 如果临时开发环境不想跑 migration，可显式设置 `AUTO_CREATE_TABLES=true`，但 README 应推荐迁移命令作为标准路径。

### 测试环境

1. 测试配置 `APP_ENV=test`。
2. 测试数据库通过 migration 或测试 fixture 初始化。
3. 单元测试中仍可针对 isolated engine 调用 `Base.metadata.create_all`，但应用启动路径不应依赖自动建表。

### 生产环境

1. 部署前运行 Alembic migration。
2. 配置 `APP_ENV=production`。
3. 配置 `AUTO_CREATE_TABLES=false`。
4. 配置非空且不包含 wildcard 的 `CORS_ALLOW_ORIGINS`。
5. 应用启动时不会自动创建表。

## 错误处理

- Alembic 读取不到有效 `DATABASE_URL`：迁移命令失败，提示检查环境变量。
- `APP_ENV=production` 且 `AUTO_CREATE_TABLES=true`：配置加载失败，应用不启动。
- `APP_ENV=production` 且 CORS 为空或包含 `*`：配置加载失败，应用不启动。
- initial migration 与当前模型不一致：以模型测试和 migration 执行结果为准，修正 migration 后再继续。

## 测试策略

### 配置测试

- `APP_ENV=production` + `AUTO_CREATE_TABLES=true` 抛出配置错误。
- `APP_ENV=production` + `CORS_ALLOW_ORIGINS=*` 抛出配置错误。
- `CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:4200` 解析为两个 origin。
- development/test 环境允许 `AUTO_CREATE_TABLES=true`。

### 启动测试

- `AUTO_CREATE_TABLES=false` 时 lifespan 不调用 `init_db()`。
- `AUTO_CREATE_TABLES=true` 且非 production 时 lifespan 调用 `init_db()`。
- FastAPI app 的 CORS middleware 使用 settings 中的 origin list。

### 迁移验证

- 在空数据库上执行 `pnpm nx run luna-corpus:db-migrate`，应创建当前四类业务表。
- 执行后应用可启动并访问健康检查。
- 后续生成 migration 时，Alembic 能读取 `Base.metadata`。

### 文档验证

- README 中的迁移命令、启动命令、环境变量名与实际 target/config 保持一致。
- `.env.example` 包含 `APP_ENV`、`AUTO_CREATE_TABLES`、`CORS_ALLOW_ORIGINS`。

## 验收标准

- `luna-corpus` 有可运行的 Alembic initial migration。
- 生产环境不会执行自动建表。
- CORS 不再硬编码允许所有来源。
- 可通过 Nx target 执行数据库迁移。
- README 说明迁移和配置流程。
- 后续 P0-M2 可直接新增模型并生成下一条 migration。

## 实施顺序

1. 添加 Alembic 依赖和配置文件。
2. 生成 initial migration。
3. 扩展 Settings 并增加配置校验。
4. 修改 FastAPI lifespan 和 CORS 配置。
5. 添加 Nx migration targets。
6. 更新 `.env.example` 和 README。
7. 补充配置、启动、迁移相关测试。
8. 通过 Nx 运行测试和迁移验证。
