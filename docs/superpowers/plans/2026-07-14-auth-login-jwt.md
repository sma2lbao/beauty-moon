# 真实登录认证（密码登录 + 自签发 JWT）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用密码登录 + 自签发 JWT 替换现有 `X-User-Id` header 信任链，彻底消灭身份伪造漏洞。

**Architecture:** 系统自管用户名/密码（bcrypt 哈希）。登录签发短期无状态 access token（JWT）+ 长期有状态 refresh token（SHA-256 存库、可撤销）。所有受保护路由从 `Authorization: Bearer <token>` 解析身份，资源上下文 header（`X-Tenant-Id`/`X-Workspace-Id`/`X-Knowledge-Base-Id`）保持不变。首个 admin 由 seed 脚本创建，其余用户由 admin 经 API 创建。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、`python-jose[cryptography]`（JWT）、`passlib[bcrypt]`（密码哈希）、pytest。

## Global Constraints

- 包管理器统一 `uv` / `npm exec nx`，禁止 `pip`/`pnpm`。
- 迁移用 Alembic，生产禁止 `create_all`；新迁移跟在 `20260714_0013_cost_quota` 之后。
- 所有交流、注释、commit message 遵循仓库现状（代码注释用英文，与现有一致）。
- `access_token_expire_minutes=15`、`refresh_token_expire_days=7`、`jwt_algorithm="HS256"`（verbatim）。
- 登录失败统一返回 `401 "Invalid credentials"`，不区分邮箱/密码错误（防用户枚举）。
- 资源上下文 header 名不变：`X-Tenant-Id`、`X-Workspace-Id`、`X-Knowledge-Base-Id`。
- 测试用 sqlite in-memory（沿用 `tests/api/test_file_upload.py` 的 `app_db`/`client` 模式）。

---

### Task 1: JWT 配置项与生产校验

**Files:**
- Modify: `apps/luna-corpus/pyproject.toml`
- Modify: `apps/luna-corpus/app/core/config.py`
- Test: `apps/luna-corpus/tests/core/test_auth_config.py`

**Interfaces:**
- Produces: `Settings.jwt_secret_key: str`、`Settings.jwt_algorithm: str`、`Settings.access_token_expire_minutes: int`、`Settings.refresh_token_expire_days: int`；生产环境下 `jwt_secret_key` 为空即抛 `ValueError`。

- [ ] **Step 1: 添加依赖**

在 `apps/luna-corpus/pyproject.toml` 的 `[project]` `dependencies` 数组中追加两行（保持数组其他项不动）：

```toml
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "bcrypt<4.1.0",
```

> 说明：`bcrypt<4.1.0` 用于规避 passlib 1.7.4 读取 bcrypt 版本时的兼容告警。

安装：

```bash
cd /Users/sma2lbao/Code/beauty-moon && npm exec nx run luna-corpus:install 2>/dev/null || (cd apps/luna-corpus && uv sync)
```

- [ ] **Step 2: 写失败测试**

创建 `apps/luna-corpus/tests/core/test_auth_config.py`：

```python
"""Tests for JWT-related settings and production validation."""
import pytest

from app.core.config import AppEnv, Settings


def test_jwt_defaults_present_in_development():
    settings = Settings(app_env=AppEnv.DEVELOPMENT)
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 15
    assert settings.refresh_token_expire_days == 7
    assert settings.jwt_secret_key  # dev 有默认值


def test_production_requires_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            app_env=AppEnv.PRODUCTION,
            auto_create_tables=False,
            cors_allow_origins=["https://app.example.com"],
            jwt_secret_key="",
        )
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd apps/luna-corpus && uv run pytest tests/core/test_auth_config.py -v`
Expected: FAIL（`jwt_secret_key` 等字段不存在 / 生产不校验）

- [ ] **Step 4: 实现配置字段与校验**

在 `apps/luna-corpus/app/core/config.py` 的 `Settings` 类里，找到已有字段区（如 `conversation_max_tokens` 附近），新增字段：

```python
    # Authentication (JWT)
    jwt_secret_key: str = Field(
        default="dev-insecure-secret-change-me",
        description="Secret key for signing JWT access tokens; must be set in production",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    access_token_expire_minutes: int = Field(
        default=15, description="Access token lifetime in minutes"
    )
    refresh_token_expire_days: int = Field(
        default=7, description="Refresh token lifetime in days"
    )
```

在已有的 `validate_production_safety` 方法内（`if "*" in self.cors_allow_origins:` 分支之后、`return self` 之前）追加：

```python
        if not self.jwt_secret_key or self.jwt_secret_key == "dev-insecure-secret-change-me":
            raise ValueError("JWT_SECRET_KEY must be set to a secure value in production")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/luna-corpus && uv run pytest tests/core/test_auth_config.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/pyproject.toml apps/luna-corpus/uv.lock apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/core/test_auth_config.py
git commit -m "feat(auth): add JWT settings and production secret validation"
```

---

### Task 2: 密码哈希模块

**Files:**
- Create: `apps/luna-corpus/app/auth/password.py`
- Test: `apps/luna-corpus/tests/auth/test_password.py`

**Interfaces:**
- Produces: `hash_password(raw: str) -> str`、`verify_password(raw: str, hashed: str) -> bool`。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/auth/test_password.py`（若无 `tests/auth/__init__.py` 一并创建空文件）：

```python
"""Tests for bcrypt password hashing."""
from app.auth.password import hash_password, verify_password


def test_hash_is_not_plaintext():
    hashed = hash_password("s3cret-pw")
    assert hashed != "s3cret-pw"
    assert hashed.startswith("$2")  # bcrypt prefix


def test_verify_correct_password():
    hashed = hash_password("s3cret-pw")
    assert verify_password("s3cret-pw", hashed) is True


def test_verify_wrong_password():
    hashed = hash_password("s3cret-pw")
    assert verify_password("wrong", hashed) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && uv run pytest tests/auth/test_password.py -v`
Expected: FAIL（`app.auth.password` 不存在）

- [ ] **Step 3: 实现**

创建 `apps/luna-corpus/app/auth/password.py`：

```python
"""Password hashing utilities backed by bcrypt."""
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw: str) -> str:
    """Return a bcrypt hash of the given plaintext password."""
    return _pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    """Return True if the plaintext matches the stored hash."""
    return _pwd_context.verify(raw, hashed)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && uv run pytest tests/auth/test_password.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/app/auth/password.py apps/luna-corpus/tests/auth/
git commit -m "feat(auth): add bcrypt password hashing"
```

---

### Task 3: JWT 与 refresh token 工具

**Files:**
- Create: `apps/luna-corpus/app/auth/tokens.py`
- Test: `apps/luna-corpus/tests/auth/test_tokens.py`

**Interfaces:**
- Consumes: `Settings`（jwt_secret_key / jwt_algorithm / access_token_expire_minutes）。
- Produces:
  - `create_access_token(user_id: str) -> str`
  - `decode_access_token(token: str) -> str`（返回 user_id；无效/过期抛 `TokenError`）
  - `generate_refresh_token() -> str`（返回明文随机串）
  - `hash_refresh_token(raw: str) -> str`（SHA-256 hex）
  - 异常类 `TokenError(Exception)`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/auth/test_tokens.py`：

```python
"""Tests for JWT access tokens and refresh token helpers."""
import pytest

from app.auth.tokens import (
    TokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)


def test_access_token_roundtrip():
    token = create_access_token("user-123")
    assert decode_access_token(token) == "user-123"


def test_decode_rejects_tampered_token():
    token = create_access_token("user-123")
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(TokenError):
        decode_access_token(tampered)


def test_decode_rejects_garbage():
    with pytest.raises(TokenError):
        decode_access_token("not-a-jwt")


def test_refresh_token_is_random_and_hashable():
    a = generate_refresh_token()
    b = generate_refresh_token()
    assert a != b
    assert hash_refresh_token(a) == hash_refresh_token(a)
    assert hash_refresh_token(a) != hash_refresh_token(b)
    assert len(hash_refresh_token(a)) == 64  # sha256 hex
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && uv run pytest tests/auth/test_tokens.py -v`
Expected: FAIL（`app.auth.tokens` 不存在）

- [ ] **Step 3: 实现**

创建 `apps/luna-corpus/app/auth/tokens.py`：

```python
"""JWT access tokens and opaque refresh token helpers."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import get_settings


class TokenError(Exception):
    """Raised when an access token is missing, invalid, or expired."""


def create_access_token(user_id: str) -> str:
    """Sign a short-lived JWT access token carrying the user id as subject."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """Validate a JWT access token and return the subject (user id)."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise TokenError("Invalid or expired token") from exc
    sub = payload.get("sub")
    if not sub or payload.get("type") != "access":
        raise TokenError("Malformed token payload")
    return sub


def generate_refresh_token() -> str:
    """Return a cryptographically random opaque refresh token."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    """Return the SHA-256 hex digest used to store refresh tokens."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

> 注：若 `app/core/config.py` 未导出 `get_settings`，改用现有获取 settings 的方式（检查 `config.py` 底部的 `settings = Settings()` 或 `get_settings()` 定义，与之保持一致）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && uv run pytest tests/auth/test_tokens.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/app/auth/tokens.py apps/luna-corpus/tests/auth/test_tokens.py
git commit -m "feat(auth): add JWT access tokens and refresh token helpers"
```

---

### Task 4: 数据模型与迁移（User.hashed_password + RefreshToken）

**Files:**
- Modify: `apps/luna-corpus/app/db/models.py`
- Create: `apps/luna-corpus/alembic/versions/20260714_0014_auth_login.py`
- Test: `apps/luna-corpus/tests/db/test_auth_models.py`

**Interfaces:**
- Produces: `User.hashed_password: Mapped[str | None]`；`RefreshToken` 模型（字段 id/user_id/token_hash/expires_at/revoked_at/created_at；关系 `user`）。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/db/test_auth_models.py`：

```python
"""Tests for auth-related model columns and RefreshToken table."""
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, RefreshToken, User


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_user_has_hashed_password_column():
    session = _session()
    user = User(email="a@example.com", display_name="A", hashed_password="hashed")
    session.add(user)
    session.commit()
    assert session.query(User).first().hashed_password == "hashed"


def test_refresh_token_persist_and_revoke():
    session = _session()
    user = User(email="b@example.com", display_name="B", hashed_password="h")
    session.add(user)
    session.commit()
    rt = RefreshToken(
        user_id=user.id,
        token_hash="deadbeef",
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    session.add(rt)
    session.commit()
    stored = session.query(RefreshToken).first()
    assert stored.revoked_at is None
    assert stored.user_id == user.id
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && uv run pytest tests/db/test_auth_models.py -v`
Expected: FAIL（`hashed_password` 列 / `RefreshToken` 不存在）

- [ ] **Step 3: 修改 User 模型**

在 `apps/luna-corpus/app/db/models.py` 的 `User` 类中，`is_active` 字段之后新增：

```python
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

同时把 `User` 类的 docstring 从 `"""Application identity resolved from temporary request headers."""` 改为：

```python
    """Application user authenticated by password login."""
```

- [ ] **Step 4: 新增 RefreshToken 模型**

在 `apps/luna-corpus/app/db/models.py` 的 `User` 类定义之后新增（`Index` 已在文件顶部导入）：

```python
class RefreshToken(Base):
    """Server-side refresh token record; stores a SHA-256 hash, never plaintext."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User")

    __table_args__ = (Index("ix_refresh_tokens_user_id", "user_id"),)
```

- [ ] **Step 5: 运行模型测试确认通过**

Run: `cd apps/luna-corpus && uv run pytest tests/db/test_auth_models.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 生成迁移**

```bash
cd /Users/sma2lbao/Code/beauty-moon
npm exec nx run luna-corpus:db-revision -- --autogenerate -m "auth login: user password + refresh tokens" 2>/dev/null \
  || (cd apps/luna-corpus && uv run alembic revision --autogenerate -m "auth login: user password + refresh tokens")
```

打开生成的迁移文件，确认 `upgrade()` 含 `add_column('users', ... 'hashed_password' ...)` 与 `create_table('refresh_tokens', ...)`，`downgrade()` 含对应的 `drop_column` / `drop_table`。若自动生成把文件命名为别的时间戳，重命名为 `20260714_0014_auth_login.py` 并将 `down_revision` 指向 `20260714_0013_cost_quota` 的 revision id。

- [ ] **Step 7: 应用迁移验证可执行**

```bash
cd apps/luna-corpus && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```

Expected: 三条命令均无报错（可正常 upgrade/downgrade/再 upgrade）。

- [ ] **Step 8: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/alembic/versions/ apps/luna-corpus/tests/db/test_auth_models.py
git commit -m "feat(auth): add hashed_password column and refresh_tokens table"
```

---

### Task 5: 认证业务逻辑 service

**Files:**
- Create: `apps/luna-corpus/app/auth/service.py`
- Test: `apps/luna-corpus/tests/auth/test_service.py`

**Interfaces:**
- Consumes: `hash_password`/`verify_password`（Task 2）、`create_access_token`/`generate_refresh_token`/`hash_refresh_token`（Task 3）、`User`/`RefreshToken`（Task 4）。
- Produces:
  - `TokenPair`（dataclass：`access_token: str`、`refresh_token: str`、`expires_in: int`）
  - `authenticate(db, email, password) -> User`（失败抛 `AuthError`）
  - `issue_token_pair(db, user) -> TokenPair`
  - `rotate_refresh_token(db, raw_refresh) -> TokenPair`（旧的置 revoked，发新对；无效抛 `AuthError`）
  - `revoke_refresh_token(db, raw_refresh) -> None`
  - 异常类 `AuthError(Exception)`

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/auth/test_service.py`：

```python
"""Tests for authentication service logic."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.password import hash_password
from app.auth.service import (
    AuthError,
    authenticate,
    issue_token_pair,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.db.models import Base, RefreshToken, User


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    user = User(
        email="u@example.com",
        display_name="U",
        hashed_password=hash_password("correct-pw"),
    )
    session.add(user)
    session.commit()
    yield session, user
    session.close()


def test_authenticate_success(db):
    session, user = db
    assert authenticate(session, "u@example.com", "correct-pw").id == user.id


def test_authenticate_wrong_password(db):
    session, _ = db
    with pytest.raises(AuthError):
        authenticate(session, "u@example.com", "wrong")


def test_authenticate_unknown_email(db):
    session, _ = db
    with pytest.raises(AuthError):
        authenticate(session, "nobody@example.com", "correct-pw")


def test_issue_and_rotate(db):
    session, user = db
    pair = issue_token_pair(session, user)
    assert pair.access_token and pair.refresh_token
    assert session.query(RefreshToken).filter_by(revoked_at=None).count() == 1

    new_pair = rotate_refresh_token(session, pair.refresh_token)
    assert new_pair.refresh_token != pair.refresh_token
    # 旧 refresh 已被撤销，不能再次轮换
    with pytest.raises(AuthError):
        rotate_refresh_token(session, pair.refresh_token)


def test_revoke(db):
    session, user = db
    pair = issue_token_pair(session, user)
    revoke_refresh_token(session, pair.refresh_token)
    with pytest.raises(AuthError):
        rotate_refresh_token(session, pair.refresh_token)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && uv run pytest tests/auth/test_service.py -v`
Expected: FAIL（`app.auth.service` 不存在）

- [ ] **Step 3: 实现**

创建 `apps/luna-corpus/app/auth/service.py`：

```python
"""Authentication business logic: login, token issuance, rotation, revocation."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.auth.password import verify_password
from app.auth.tokens import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from app.core.config import get_settings
from app.db.models import RefreshToken, User


class AuthError(Exception):
    """Raised on failed authentication or invalid refresh token."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def authenticate(db: Session, email: str, password: str) -> User:
    """Return the user if email+password match and the account is active."""
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.hashed_password:
        raise AuthError("Invalid credentials")
    if not verify_password(password, user.hashed_password):
        raise AuthError("Invalid credentials")
    if not user.is_active:
        raise AuthError("Invalid credentials")
    return user


def issue_token_pair(db: Session, user: User) -> TokenPair:
    """Create a new access token and persist a fresh refresh token record."""
    settings = get_settings()
    raw_refresh = generate_refresh_token()
    record = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(record)
    db.commit()
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=raw_refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _load_valid_refresh(db: Session, raw_refresh: str) -> RefreshToken:
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(raw_refresh))
        .first()
    )
    if not record or record.revoked_at is not None:
        raise AuthError("Invalid refresh token")
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise AuthError("Invalid refresh token")
    return record


def rotate_refresh_token(db: Session, raw_refresh: str) -> TokenPair:
    """Revoke the presented refresh token and issue a new token pair."""
    record = _load_valid_refresh(db, raw_refresh)
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    user = db.query(User).filter(User.id == record.user_id).first()
    if not user or not user.is_active:
        raise AuthError("Invalid refresh token")
    return issue_token_pair(db, user)


def revoke_refresh_token(db: Session, raw_refresh: str) -> None:
    """Mark the presented refresh token as revoked (logout)."""
    record = _load_valid_refresh(db, raw_refresh)
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && uv run pytest tests/auth/test_service.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/app/auth/service.py apps/luna-corpus/tests/auth/test_service.py
git commit -m "feat(auth): add authentication service with token rotation"
```

---

### Task 6: 认证端点 auth_routes 与挂载

**Files:**
- Create: `apps/luna-corpus/app/api/auth_routes.py`
- Modify: `apps/luna-corpus/app/main.py`
- Test: `apps/luna-corpus/tests/api/test_auth_routes.py`

**Interfaces:**
- Consumes: `authenticate`/`issue_token_pair`/`rotate_refresh_token`/`revoke_refresh_token`/`AuthError`（Task 5）、`decode_access_token`/`TokenError`（Task 3）。
- Produces: `auth_router`（prefix `/api/v1/auth`），端点 `POST /login`、`POST /refresh`、`POST /logout`、`GET /me`。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/api/test_auth_routes.py`：

```python
"""Integration tests for /api/v1/auth endpoints."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.password import hash_password
from app.db.database import get_db
from app.db.models import Base, User
from app.main import create_app


@pytest.fixture
def client_and_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        User(
            email="login@example.com",
            display_name="Login",
            hashed_password=hash_password("pw12345"),
        )
    )
    session.commit()
    session.close()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_login_success(client_and_session):
    resp = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "pw12345"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_login_wrong_password(client_and_session):
    resp = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "nope"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


def test_me_with_access_token(client_and_session):
    login = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "pw12345"},
    ).json()
    resp = client_and_session.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "login@example.com"


def test_refresh_rotates(client_and_session):
    login = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "pw12345"},
    ).json()
    resp = client_and_session.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert resp.status_code == 200
    assert resp.json()["refresh_token"] != login["refresh_token"]


def test_logout_then_refresh_rejected(client_and_session):
    login = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "pw12345"},
    ).json()
    client_and_session.post(
        "/api/v1/auth/logout", json={"refresh_token": login["refresh_token"]}
    )
    resp = client_and_session.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && uv run pytest tests/api/test_auth_routes.py -v`
Expected: FAIL（`/api/v1/auth/login` 404 / `auth_router` 不存在）

- [ ] **Step 3: 实现端点**

创建 `apps/luna-corpus/app/api/auth_routes.py`：

```python
"""Authentication endpoints: login, refresh, logout, me."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth.service import (
    AuthError,
    authenticate,
    issue_token_pair,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.auth.tokens import TokenError, decode_access_token
from app.db.database import get_db
from app.db.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    try:
        user = authenticate(db, payload.email, payload.password)
    except AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    pair = issue_token_pair(db, user)
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Annotated[Session, Depends(get_db)]):
    try:
        pair = rotate_refresh_token(db, payload.refresh_token)
    except AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: Annotated[Session, Depends(get_db)]):
    try:
        revoke_refresh_token(db, payload.refresh_token)
    except AuthError:
        pass  # logout is idempotent; unknown/expired tokens are a no-op
    return None


@router.get("/me", response_model=MeResponse)
def me(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )
    try:
        user_id = decode_access_token(authorization.removeprefix("Bearer "))
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    return MeResponse(id=user.id, email=user.email, display_name=user.display_name)
```

- [ ] **Step 4: 挂载 router**

在 `apps/luna-corpus/app/main.py` 中，仿照现有 import 补：

```python
from app.api.auth_routes import router as auth_router
```

在现有 `app.include_router(router)` 之前（让 auth 端点优先）新增：

```python
    app.include_router(auth_router)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/luna-corpus && uv run pytest tests/api/test_auth_routes.py -v`
Expected: PASS（5 passed）

> 若 `EmailStr` 报缺少 `email-validator`，在 pyproject 依赖追加 `"email-validator>=2.0.0"` 后 `uv sync` 重试。

- [ ] **Step 6: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/app/api/auth_routes.py apps/luna-corpus/app/main.py apps/luna-corpus/tests/api/test_auth_routes.py apps/luna-corpus/pyproject.toml apps/luna-corpus/uv.lock
git commit -m "feat(auth): add login/refresh/logout/me endpoints"
```

---

### Task 7: 身份链路切换（X-User-Id → Bearer token）+ 测试 fixture 迁移

> 本任务是本计划核心。切换身份来源会同时影响所有现有受保护路由测试，因此 fixture helper 的更新必须与切换在同一任务内完成，否则测试全红、无法独立验收。

**Files:**
- Modify: `apps/luna-corpus/app/api/auth.py`
- Modify: `apps/luna-corpus/tests/api/test_file_upload.py:95`（`_auth_headers` helper）
- Test: `apps/luna-corpus/tests/api/test_auth_enforcement.py`（新增回归测试）

**Interfaces:**
- Consumes: `decode_access_token`/`TokenError`（Task 3）、`create_access_token`（Task 3，测试 helper 用）。
- Produces: `get_authenticated_context` 与 `require_permission` 对外签名不变（仍返回 `AuthenticatedRequestContext`），内部身份来源改为 `Authorization` header。

- [ ] **Step 1: 写回归失败测试**

创建 `apps/luna-corpus/tests/api/test_auth_enforcement.py`：

```python
"""Regression: forged headers must not authenticate; only valid tokens pass."""
from tests.api.test_file_upload import (
    app_db,  # noqa: F401
    client,  # noqa: F401
    create_user_with_permissions,
)
from app.auth.permissions import PermissionSlug


def test_forged_x_user_id_is_rejected(client, app_db):
    """A raw X-User-Id header must no longer grant access."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session, context["workspace_id"], "reader", [PermissionSlug.DOCUMENT_READ]
    )
    resp = client.get(
        "/api/v1/documents",
        headers={
            "X-User-Id": user_id,  # forged legacy header, no bearer token
            "X-Tenant-Id": context["tenant_id"],
            "X-Workspace-Id": context["workspace_id"],
            "X-Knowledge-Base-Id": context["kb_one_id"],
        },
    )
    assert resp.status_code == 401


def test_valid_bearer_token_is_accepted(client, app_db):
    from app.auth.tokens import create_access_token

    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session, context["workspace_id"], "reader", [PermissionSlug.DOCUMENT_READ]
    )
    resp = client.get(
        "/api/v1/documents",
        headers={
            "Authorization": f"Bearer {create_access_token(user_id)}",
            "X-Tenant-Id": context["tenant_id"],
            "X-Workspace-Id": context["workspace_id"],
            "X-Knowledge-Base-Id": context["kb_one_id"],
        },
    )
    assert resp.status_code == 200
```

> 注：确认 `/api/v1/documents` 列表端点存在且需 `DOCUMENT_READ`；若路径不同，改成实际的受保护 GET 端点。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && uv run pytest tests/api/test_auth_enforcement.py -v`
Expected: FAIL（forged header 仍返回 200，因为尚未切换）

- [ ] **Step 3: 切换 auth.py 身份来源**

在 `apps/luna-corpus/app/api/auth.py`：

顶部 import 处新增：

```python
from app.auth.tokens import TokenError, decode_access_token
```

将 `get_authenticated_context` 的签名参数 `x_user_id: str | None` 替换为 `token: str | None`，并把函数体开头的 user 解析逻辑替换：

原：

```python
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-User-Id",
        )

    user = db.query(User).filter(User.id == x_user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
```

改为：

```python
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    try:
        user_id = decode_access_token(token)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
```

在 `require_permission` 的内层 `dependency` 函数中，将参数：

```python
        x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
```

替换为：

```python
        authorization: Annotated[str | None, Header()] = None,
```

并在调用 `get_authenticated_context` 时把 `x_user_id=x_user_id` 改为：

```python
            token=(
                authorization.removeprefix("Bearer ")
                if authorization and authorization.startswith("Bearer ")
                else None
            ),
```

- [ ] **Step 4: 迁移 `_auth_headers` helper**

在 `apps/luna-corpus/tests/api/test_file_upload.py` 顶部 import 区新增：

```python
from app.auth.tokens import create_access_token
```

将 `_auth_headers` 函数（约 95 行）整体替换为：

```python
def _auth_headers(context, knowledge_base_id="kb-1", user_id="user-1"):
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }
```

- [ ] **Step 5: 运行回归测试确认通过**

Run: `cd apps/luna-corpus && uv run pytest tests/api/test_auth_enforcement.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 运行全部 api 测试确认无回归**

Run: `cd apps/luna-corpus && uv run pytest tests/api -v`
Expected: 全部 PASS。若个别测试直接手写 `X-User-Id` 而未走 `_auth_headers`，逐个改为 `Authorization: Bearer {create_access_token(<user_id>)}`（搜索命令：`grep -rn "X-User-Id" tests/`）。

- [ ] **Step 7: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/app/api/auth.py apps/luna-corpus/tests/
git commit -m "feat(auth): authenticate from bearer token, drop X-User-Id trust"
```

---

### Task 8: 保护裸露的租户/工作区/知识库端点

**Files:**
- Modify: `apps/luna-corpus/app/api/tenant_routes.py`
- Test: `apps/luna-corpus/tests/api/test_tenant_auth.py`

**Interfaces:**
- Consumes: `require_permission`（`app/api/auth.py`）、`PermissionSlug`（`app/auth/permissions.py`）。

> 说明：`create_tenant` 是租户创建，逻辑上先于任何 workspace membership，无法用 workspace 级权限保护——它应保留给 seed/平台运维（见 Task 9 的 seed 脚本或独立平台密钥），本任务**不改 `create_tenant`**。`create_workspace`/`create_knowledge_base`/各 `list_*` 端点绑定到已存在的 tenant/workspace，可用 `WORKSPACE_MANAGE`/`WORKSPACE_READ` 保护。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/api/test_tenant_auth.py`：

```python
"""Tenant/workspace/kb management endpoints require authentication."""
from tests.api.test_file_upload import app_db, client  # noqa: F401


def test_create_workspace_requires_auth(client, app_db):
    _, _, context = app_db
    resp = client.post(
        "/api/v1/workspaces",
        json={"name": "New", "slug": "new", "tenant_id": context["tenant_id"]},
    )
    assert resp.status_code == 401


def test_list_knowledge_bases_requires_auth(client, app_db):
    resp = client.get("/api/v1/knowledge-bases")
    assert resp.status_code == 401
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && uv run pytest tests/api/test_tenant_auth.py -v`
Expected: FAIL（当前无认证，返回 200/201 或 422 而非 401）

- [ ] **Step 3: 给端点加权限依赖**

在 `apps/luna-corpus/app/api/tenant_routes.py` 顶部 import：

```python
from typing import Annotated

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
```

为 `create_workspace`、`create_knowledge_base` 添加写权限依赖，为 `list_workspaces`、`list_knowledge_bases` 添加读权限依赖。示例（`create_workspace`）：

```python
@router.post(
    "/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace(
    payload: WorkspaceCreate,
    db: Annotated[Session, Depends(get_db)],
    _ctx: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.WORKSPACE_MANAGE)),
    ],
):
    ...  # 函数体不变
```

对 `list_*` 用 `PermissionSlug.WORKSPACE_READ`。保持各函数原有业务逻辑不变，仅新增依赖参数。

> `require_permission` 依赖会要求 `X-Tenant-Id`/`X-Workspace-Id`/`X-Knowledge-Base-Id` 上下文 header；测试请求需带上（见 Step 4）。

- [ ] **Step 4: 更新测试为带 token 的正向用例**

将 `tests/api/test_tenant_auth.py` 追加一个正向测试，确认带权限 token 可创建（复用 `create_user_with_permissions` 与 `_auth_headers`）：

```python
from tests.api.test_file_upload import create_user_with_permissions, _auth_headers
from app.auth.permissions import PermissionSlug


def test_create_workspace_with_permission(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session, context["workspace_id"], "wsadmin", [PermissionSlug.WORKSPACE_MANAGE]
    )
    headers = _auth_headers(context, knowledge_base_id=context["kb_one_id"], user_id=user_id)
    resp = client.post(
        "/api/v1/workspaces",
        json={"name": "New", "slug": "new-ws", "tenant_id": context["tenant_id"]},
        headers=headers,
    )
    assert resp.status_code == 201
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/luna-corpus && uv run pytest tests/api/test_tenant_auth.py -v`
Expected: PASS（3 passed）

- [ ] **Step 6: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/app/api/tenant_routes.py apps/luna-corpus/tests/api/test_tenant_auth.py
git commit -m "feat(auth): protect workspace/kb management endpoints with RBAC"
```

---

### Task 9: 创建用户端点 + seed admin 脚本

**Files:**
- Modify: `apps/luna-corpus/app/api/tenant_routes.py`（或复用现有用户管理位置；本计划放在 tenant_routes 同文件的用户区）
- Create: `apps/luna-corpus/scripts/seed_admin.py`
- Test: `apps/luna-corpus/tests/api/test_user_management.py`

**Interfaces:**
- Consumes: `require_permission`、`PermissionSlug.WORKSPACE_MANAGE`、`hash_password`（Task 2）、`User`/`WorkspaceMembership`/`Role`（models）。
- Produces: `POST /api/v1/users` 端点；`scripts/seed_admin.py` 可执行脚本。

- [ ] **Step 1: 写失败测试**

创建 `apps/luna-corpus/tests/api/test_user_management.py`：

```python
"""Admin creates users via API; created users can log in."""
from tests.api.test_file_upload import (
    app_db,  # noqa: F401
    client,  # noqa: F401
    create_user_with_permissions,
    _auth_headers,
)
from app.auth.permissions import PermissionSlug


def test_create_user_requires_permission(client, app_db):
    resp = client.post(
        "/api/v1/users",
        json={"email": "new@example.com", "display_name": "New", "password": "pw123456"},
    )
    assert resp.status_code == 401


def test_admin_creates_user_then_login(client, app_db):
    _, Session, context = app_db
    admin_id = create_user_with_permissions(
        Session, context["workspace_id"], "admin", [PermissionSlug.WORKSPACE_MANAGE]
    )
    headers = _auth_headers(context, knowledge_base_id=context["kb_one_id"], user_id=admin_id)
    create = client.post(
        "/api/v1/users",
        json={"email": "new@example.com", "display_name": "New", "password": "pw123456"},
        headers=headers,
    )
    assert create.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "new@example.com", "password": "pw123456"},
    )
    assert login.status_code == 200
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && uv run pytest tests/api/test_user_management.py -v`
Expected: FAIL（`/api/v1/users` 404）

- [ ] **Step 3: 实现创建用户端点**

在 `apps/luna-corpus/app/api/tenant_routes.py` 追加（import 处补 `from app.auth.password import hash_password`、`from app.db.models import User`、`from pydantic import BaseModel, EmailStr`，若已有则跳过）：

```python
class UserCreate(BaseModel):
    email: EmailStr
    display_name: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str


@router.post(
    "/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
    _ctx: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.WORKSPACE_MANAGE)),
    ],
):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        )
    user = User(
        email=payload.email,
        display_name=payload.display_name,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    return UserResponse(
        id=user.id, email=user.email, display_name=user.display_name
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && uv run pytest tests/api/test_user_management.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 编写 seed_admin 脚本**

创建 `apps/luna-corpus/scripts/seed_admin.py`：

```python
"""Seed the first admin user with a workspace_admin role.

Usage:
    uv run python scripts/seed_admin.py \
        --email admin@example.com --password 'secret' \
        --display-name Admin --workspace-id <workspace_id>

This is the only path that creates a user without an existing admin,
used to break the bootstrap cycle. All other users go through POST /api/v1/users.
"""
import argparse

from app.auth.password import hash_password
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS, RoleSlug
from app.db.database import SessionLocal
from app.db.models import Permission, Role, User, WorkspaceMembership


def _ensure_admin_role(session) -> Role:
    role = session.query(Role).filter(Role.slug == RoleSlug.WORKSPACE_ADMIN).first()
    if role:
        return role
    permissions = []
    for slug in DEFAULT_ROLE_PERMISSIONS[RoleSlug.WORKSPACE_ADMIN]:
        perm = session.query(Permission).filter(Permission.slug == slug).first()
        if not perm:
            perm = Permission(name=slug, slug=slug, description=slug)
            session.add(perm)
        permissions.append(perm)
    role = Role(
        name="Workspace Admin",
        slug=RoleSlug.WORKSPACE_ADMIN,
        is_system=True,
        permissions=permissions,
    )
    session.add(role)
    return role


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--workspace-id", required=True)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        if session.query(User).filter(User.email == args.email).first():
            raise SystemExit(f"User already exists: {args.email}")
        role = _ensure_admin_role(session)
        user = User(
            email=args.email,
            display_name=args.display_name,
            hashed_password=hash_password(args.password),
        )
        membership = WorkspaceMembership(
            user=user, workspace_id=args.workspace_id, roles=[role]
        )
        session.add(membership)
        session.commit()
        print(f"Created admin user {args.email} ({user.id})")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

> 校验：确认 `app.db.database` 导出 `SessionLocal`（`grep -n "SessionLocal" app/db/database.py`）。若名称不同，用实际的 session 工厂。

- [ ] **Step 6: 冒烟验证脚本参数解析**

Run: `cd apps/luna-corpus && uv run python scripts/seed_admin.py --help`
Expected: 打印 usage，含 `--email --password --display-name --workspace-id`

- [ ] **Step 7: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/app/api/tenant_routes.py apps/luna-corpus/scripts/seed_admin.py apps/luna-corpus/tests/api/test_user_management.py
git commit -m "feat(auth): add admin user creation endpoint and seed script"
```

---

### Task 10: 文档与环境说明

**Files:**
- Modify: `apps/luna-corpus/.env.example`
- Modify: `apps/luna-corpus/README.md`

**Interfaces:** 无代码接口，仅文档。

- [ ] **Step 1: 更新 .env.example**

在 `apps/luna-corpus/.env.example` 追加认证配置区：

```bash
# Authentication (JWT)
JWT_SECRET_KEY=dev-insecure-secret-change-me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
```

- [ ] **Step 2: 更新 README 认证章节**

在 `apps/luna-corpus/README.md` 的环境说明之后新增 `## Authentication` 章节：

````markdown
## Authentication

All protected endpoints require a JWT access token in the `Authorization: Bearer <token>` header. Resource-scope headers (`X-Tenant-Id`, `X-Workspace-Id`, `X-Knowledge-Base-Id`) are still required to select the knowledge base context.

### Bootstrap the first admin

The first admin must be created via the seed script (no API access exists yet):

```bash
cd apps/luna-corpus
uv run python scripts/seed_admin.py \
  --email admin@example.com --password 'change-me' \
  --display-name Admin --workspace-id <workspace_id>
```

### Login flow

```bash
# 1. Login -> access_token + refresh_token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"change-me"}'

# 2. Call protected endpoints
curl http://localhost:8000/api/v1/documents \
  -H 'Authorization: Bearer <access_token>' \
  -H 'X-Tenant-Id: ...' -H 'X-Workspace-Id: ...' -H 'X-Knowledge-Base-Id: ...'

# 3. Refresh when access token expires (rotates refresh token)
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<refresh_token>"}'

# 4. Logout (revoke refresh token)
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<refresh_token>"}'
```

Production must set a strong `JWT_SECRET_KEY`; the app refuses to start otherwise.
````

- [ ] **Step 3: 提交**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add apps/luna-corpus/.env.example apps/luna-corpus/README.md
git commit -m "docs(auth): document login flow and admin bootstrap"
```

---

### Task 11: 全量测试与收尾

**Files:** 无新增，验证整体。

- [ ] **Step 1: 运行完整测试套件**

Run: `cd apps/luna-corpus && uv run pytest -q`
Expected: 全部 PASS。若有失败，多半是残留的 `X-User-Id` 手写 header —— `grep -rn "X-User-Id" tests/` 定位并改为 bearer token。

- [ ] **Step 2: 运行 lint**

Run: `cd /Users/sma2lbao/Code/beauty-moon && npm exec nx run luna-corpus:lint`
Expected: PASS（或按提示修复 import 顺序等）

- [ ] **Step 3: 确认无残留信任漏洞**

Run: `cd apps/luna-corpus && grep -rn "X-User-Id" app/`
Expected: 无输出（app 代码中不再读取该 header）

- [ ] **Step 4: 最终提交（若 lint 有改动）**

```bash
cd /Users/sma2lbao/Code/beauty-moon
git add -A && git commit -m "chore(auth): lint fixes and cleanup" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:**
- 第 1 节数据模型（User.hashed_password + RefreshToken + 迁移）→ Task 4 ✅
- 第 2 节 password/tokens/service 模块 → Task 2/3/5 ✅
- 第 2 节 login/refresh/logout/me 端点 + JWT 配置 → Task 1/6 ✅
- 第 3 节身份链路切换（X-User-Id → Bearer）+ Agent 天然覆盖 → Task 7 ✅
- 第 4 节 Bootstrap（seed_admin + POST /users）→ Task 9 ✅
- 第 4 节 顺手保护裸露 tenant/workspace 端点 → Task 8 ✅
- 第 4 节 错误处理（统一 401 Invalid credentials）→ Task 5/6 ✅
- 第 4 节 测试策略（单元/集成/回归/fixture 迁移）→ Task 2/3/5/6/7 ✅
- 文档（.env.example / README）→ Task 10 ✅

**放宽项说明**：spec 写“给 create_tenant/workspace/kb 补 require_permission”，实施时发现 `create_tenant` 存在 bootstrap 悖论（租户创建先于任何 membership），故 Task 8 只保护 workspace/kb 端点，`create_tenant` 保留给 seed/平台运维。此为合理收窄，已在 Task 8 说明。

**Placeholder scan:** 无 TBD/TODO；所有代码步骤含完整代码。

**Type consistency:** `TokenPair`/`AuthError`/`TokenError`/`decode_access_token`/`create_access_token`/`issue_token_pair`/`rotate_refresh_token`/`revoke_refresh_token`/`hash_refresh_token`/`generate_refresh_token` 在定义任务（3/5）与消费任务（6/7）间签名一致。`_auth_headers(context, knowledge_base_id, user_id)` 签名在 Task 7 迁移后保持原参数，Task 8/9 调用方式兼容。
