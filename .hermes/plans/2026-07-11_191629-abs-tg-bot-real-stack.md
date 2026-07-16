# MoYin.CC ABS + Telegram Bot 真实环境实施计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 基于本机已运行的 `/root/audiobookshelf-portal`、Audiobookshelf 容器和现有 Web 自助账号系统，新增 Telegram Bot，使 TG 用户可以绑定已有 Web 账号、查询账号/书库数据，并把后续开号/续期流程接入 Bot。

**Architecture:** 保持 `moyin-api` 作为唯一账号与业务中心，Telegram Bot 只做交互层；Bot 通过 Docker 内网调用 `moyin-api` 的内部接口，`moyin-api` 继续统一访问 SQLite 数据库和 Audiobookshelf API。已有 Web 端继续负责安全敏感操作，例如登录态生成绑定码、修改密码、注册/续期。

**Tech Stack:** FastAPI + SQLModel + SQLite + httpx；Next.js 16 + React 19；Docker Compose；Audiobookshelf 2.35.1；Telegram Bot 长轮询 polling。

---

## 0. 已核实的本机现状

### Docker 服务

真实运行中的相关服务如下：

| 服务/容器 | 作用 | 镜像/技术 | 端口/网络 |
|---|---|---|---|
| `moyin-api` | Portal 后端 API | FastAPI / Python 3.13 | `127.0.0.1:8019 -> 8000`，网络 `audiobookshelf-portal_default` |
| `moyin-web` | Web 自助面板 | Next.js / Node | `127.0.0.1:3009 -> 3009`，网络 `audiobookshelf-portal_default` |
| `moyin-worker` | 后台巡检 worker | Python `app.worker --interval 300` | 同网络，使用 `moyin-data` volume |
| `audiobookshelf` | ABS 服务 | `ghcr.io/advplyr/audiobookshelf` `2.35.1` | `0.0.0.0:13268 -> 80`，默认 `bridge` 网络 |

Compose 文件：

```text
/root/audiobookshelf-portal/docker-compose.yml
```

当前 portal 通过 `.env` 使用：

```text
AUDIOBOOKSHELF_URL=http://172.17.0.1:13268
DATABASE_URL=sqlite:////data/portal.db
PORTAL_PUBLIC_URL=https://moyin.cc
NEXT_PUBLIC_API_BASE_URL=https://moyin.cc
```

敏感值如 `AUDIOBOOKSHELF_ADMIN_TOKEN`、`JWT_SECRET` 已存在，不应写入代码或计划明文。

### 已验证 ABS 连通性

在 `moyin-api` 容器内执行只读 smoke 测试结果：

```text
ping True
status {'isInit': True, 'language': 'zh-cn'}
libraries 1 [{'id': 'e0f89b09-f546-440d-beec-5e8b00031d4c', 'name': '内测'}]
```

说明：后端容器已经能访问 ABS API。

### 数据库现状

SQLite 数据库在容器内：

```text
/data/portal.db
```

Docker volume：

```text
audiobookshelf-portal_moyin-data
/var/lib/docker/volumes/audiobookshelf-portal_moyin-data/_data
```

当前表：

| 表 | 当前记录数 | 说明 |
|---|---:|---|
| `portal_users` | 55 | Web/Portal 用户 |
| `codes` | 5 | 注册/续期码 |
| `code_redemptions` | 37 | 卡密使用记录 |
| `audit_logs` | 25 | 管理操作审计 |
| `app_settings` | 1 | 前台配置 |

`portal_users` 已有字段：

```text
id, username, password_hash, email, telegram_id, role, status,
abs_user_id, abs_username, expires_at, created_at, updated_at, last_login_at
```

重要结论：**已经有 `telegram_id` 字段，但没有看到唯一索引，也没有 `telegram_username` / `telegram_bound_at`。第一版应复用 `telegram_id`，不要另造 `telegram_user_id`。**

### 当前后端结构

关键文件：

| 文件 | 作用 |
|---|---|
| `backend/app/models.py` | SQLModel 表定义，`PortalUser` 已包含 `telegram_id` |
| `backend/app/config.py` | Pydantic Settings，当前没有 TG Bot 配置 |
| `backend/app/db.py` | `SQLModel.metadata.create_all`，没有 Alembic/迁移系统 |
| `backend/app/abs_client.py` | Audiobookshelf REST client，已有用户创建/更新/删除、库列表、用户列表、库 item 读取 |
| `backend/app/routers/auth.py` | 登录/注册，注册时创建 ABS 用户 |
| `backend/app/routers/me.py` | 当前用户、续期、改密码 |
| `backend/app/routers/admin_users.py` | 管理员创建/禁用/删除/改密码/改有效期，同步 ABS |
| `backend/app/routers/library.py` | 用户库摘要、管理员库概览、库浏览 |
| `backend/app/main.py` | FastAPI app，注册 router，CSRF/CORS |

### 当前前端结构

关键文件：

| 文件 | 作用 |
|---|---|
| `web/lib/api.ts` | 前端 API 类型和请求封装 |
| `web/app/dashboard/page.tsx` | 用户账号中心：状态、续期、改密码、收听记录、内容概览 |
| `web/app/register/page.tsx` | 邀请码注册 |
| `web/app/admin/config/page.tsx` | 管理后台配置/用户管理/媒体库管理 |
| `web/package.json` | `npm run lint` 实际是 `tsc --noEmit` |

### 当前开号逻辑

已有两条创建用户路径：

1. 用户自助注册：`backend/app/routers/auth.py::register`
   - 校验邀请码；
   - 调用 `abs_client.create_user()`；
   - 写入 `PortalUser(abs_user_id, abs_username, expires_at, password_hash)`。

2. 管理员创建用户：`backend/app/routers/admin_users.py::create_user`
   - 管理员输入用户名、密码、有效期；
   - 调用 `abs_client.create_user()`；
   - 写入 `PortalUser` 和 `AuditLog`。

重要结论：**现有 Web 账号通常已经对应 ABS 账号。Bot 第一阶段的 `/open` 不应重复创建账号，而应做幂等检查：有 `abs_user_id` 就返回已有状态；缺失时再走统一 service 创建/修复。**

### ABS 搜索现状

已实测以下 ABS API 路径：

```text
/api/search?q=test             -> 404
/api/search?query=test         -> 404
/api/items/search?q=test       -> 404
/api/libraries/<lib_id>/items  -> 200
```

所以第一版 Bot 搜索不要依赖不存在的 `/api/search`。应先在 `moyin-api` 内复用现有 `list_libraries()` + `list_library_items()`，由 Portal 后端过滤标题/作者/演播字段。后续再查 ABS 官方文档或实际 API 后优化分页/全文搜索。

---

## 1. 总体落地方案

### 推荐最终形态

```text
Telegram 用户
  │
  ▼
新增 moyin-bot 容器，长轮询 Telegram Bot API
  │  Authorization: Bearer TELEGRAM_BOT_INTERNAL_TOKEN
  ▼
moyin-api FastAPI 内部接口
  │
  ├─ SQLite /data/portal.db
  │    ├─ portal_users.telegram_id
  │    ├─ telegram_bind_tokens
  │    └─ audit_logs
  │
  └─ Audiobookshelf API http://172.17.0.1:13268

moyin-web Dashboard
  └─ 登录后生成 Telegram 绑定码
```

### 第一版核心闭环

```text
Web 登录账号中心
  → 生成 Telegram 绑定码
  → Telegram Bot 发送 /bind <code>
  → Bot 调用 moyin-api 内部绑定接口
  → moyin-api 写入 portal_users.telegram_id
  → Bot /me 显示 Web/ABS 账号状态
  → Bot /open 幂等显示或修复 ABS 开通状态
  → Bot /library /search 读取 ABS 数据摘要
```

---

## 2. 关键设计决策

### 2.1 绑定已有账号必须从 Web 登录态发起

不让用户在 Telegram 里输入 Web 密码。

原因：

- Telegram 聊天记录不是密码输入框；
- Bot 服务不应接触用户 Web 密码；
- Web 已有登录态，最适合证明“这个人拥有该 Web 账号”；
- 一次性绑定码可过期、可审计、可撤销。

### 2.2 复用 `portal_users.telegram_id`

当前 DB 和模型已经有 `telegram_id`：

```python
telegram_id: str | None = None
```

第一版不新建 `telegram_user_id`，避免迁移/兼容混乱。需要补：

- `telegram_id` 唯一索引；
- `telegram_username`；
- `telegram_bound_at`。

### 2.3 必须补 SQLite 迁移机制

当前 `backend/app/db.py` 只有：

```python
SQLModel.metadata.create_all(engine)
```

这只能建新表，**不会给已有表加列/加索引**。因此本项目加 Telegram 功能前，必须先做轻量 idempotent SQLite migration。

建议新增：

```text
backend/app/db_migrations.py
```

由 `create_db_and_tables(engine)` 调用：

```python
SQLModel.metadata.create_all(engine)
run_sqlite_migrations(engine)
```

迁移需要可重复执行，不破坏已有 55 个用户。

### 2.4 Bot 只调内部 API，不直接读 DB/ABS

Bot 不直接挂载 `moyin-data`，也不直接持有 ABS admin token。Bot 只需要：

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_BOT_USERNAME=...
WEB_INTERNAL_API_BASE=http://moyin-api:8000
TELEGRAM_BOT_INTERNAL_TOKEN=...
```

ABS admin token 继续只在 `moyin-api` 使用。

### 2.5 `/open` 要幂等

因为 Web 注册和管理员创建已经创建 ABS 账号，所以 Bot `/open` 第一版逻辑：

| 用户状态 | `/open` 行为 |
|---|---|
| 未绑定 TG | 提示先去 Web 账号中心生成绑定码，并 `/bind` |
| 已绑定，`abs_user_id` 存在 | 返回“已开通”，显示账号状态、有效期、服务地址 |
| 已绑定，`abs_user_id` 缺失 | 后端进入修复/补开通流程；如果需要密码，优先引导用户在 Web 修改密码，不在 TG 收密码 |
| 账号 disabled/deleted | 提示联系管理员 |
| 账号 expired | 提示可续期；媒体播放受限 |

---

## 3. 后端实施计划

## Phase 1：测试与备份基线

**目标：** 在改数据库和代码前有回滚点、有当前测试基线。

**操作：**

```bash
cd /root/audiobookshelf-portal
mkdir -p backups

docker run --rm \
  -v audiobookshelf-portal_moyin-data:/data \
  -v "$PWD/backups":/backup \
  alpine sh -c 'cp /data/portal.db /backup/portal-before-tg-$(date +%F-%H%M%S).db'

cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q

cd ../web
npm run lint
```

**注意：** 当前 `/root/audiobookshelf-portal` 不是 git 仓库，`git status` 返回 `fatal: not a git repository`。正式改代码前建议至少做一个源码目录备份，或者初始化 git：

```bash
cd /root/audiobookshelf-portal
git init
git add backend web docker-compose.yml .env.example DEPLOYMENT.md
git commit -m "baseline before telegram bot integration"
```

如果不想初始化 git，也要打包备份：

```bash
cd /root
tar --exclude='audiobookshelf-portal/web/node_modules' \
    --exclude='audiobookshelf-portal/web/.next' \
    --exclude='audiobookshelf-portal/backend/.venv' \
    -czf audiobookshelf-portal-before-tg-$(date +%F-%H%M%S).tgz \
    audiobookshelf-portal
```

**验收：**

- 数据库备份文件存在；
- 后端测试基线记录清楚；
- 前端 TypeScript 基线记录清楚。

---

## Phase 2：新增轻量数据库迁移

**目标：** 安全修改已有 SQLite schema。

### 文件

Create:

```text
backend/app/db_migrations.py
backend/tests/test_db_migrations.py
```

Modify:

```text
backend/app/db.py
backend/app/models.py
```

### 数据模型调整

`backend/app/models.py`：

```python
class PortalUser(SQLModel, table=True):
    __tablename__ = "portal_users"

    ...
    telegram_id: str | None = Field(default=None, index=True)
    telegram_username: str | None = None
    telegram_bound_at: datetime | None = None
    ...


class TelegramBindToken(SQLModel, table=True):
    __tablename__ = "telegram_bind_tokens"

    id: str = Field(default_factory=new_id, primary_key=True)
    portal_user_id: str = Field(index=True)
    code_hash: str = Field(index=True, unique=True)
    expires_at: datetime
    used_at: datetime | None = None
    failed_attempts: int = 0
    created_at: datetime = Field(default_factory=utcnow)
```

### 迁移内容

`db_migrations.py` 做 idempotent SQLite 操作：

1. 检查 `portal_users` 是否有 `telegram_username`，没有则 `ALTER TABLE`。
2. 检查 `portal_users` 是否有 `telegram_bound_at`，没有则 `ALTER TABLE`。
3. 创建 `telegram_bind_tokens` 表。
4. 创建 `portal_users.telegram_id` unique partial index：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_portal_users_telegram_id
ON portal_users(telegram_id)
WHERE telegram_id IS NOT NULL AND telegram_id != '';
```

SQLite 支持 partial index，适合 nullable unique。

### TDD 测试

`backend/tests/test_db_migrations.py`：

- 从只含旧 `portal_users.telegram_id` 的内存库开始；
- 运行迁移；
- 断言新增列存在；
- 断言重复运行不报错；
- 断言两个非空相同 `telegram_id` 被 unique index 拒绝；
- 断言多个 `NULL` `telegram_id` 可共存。

**验收：**

```bash
cd /root/audiobookshelf-portal/backend
. .venv/bin/activate
pytest tests/test_db_migrations.py -q
pytest -q
```

---

## Phase 3：Telegram 绑定 service

**目标：** 把绑定码生成、校验、绑定、解绑做成后端业务服务。

### 文件

Create:

```text
backend/app/services/telegram_binding.py
backend/tests/test_telegram_binding_service.py
```

Modify:

```text
backend/app/config.py
backend/app/models.py
```

### 配置项

`backend/app/config.py` 增加：

```python
telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
telegram_bot_internal_token: str = Field(default="", alias="TELEGRAM_BOT_INTERNAL_TOKEN")
telegram_bind_code_ttl_minutes: int = Field(default=10, alias="TELEGRAM_BIND_CODE_TTL_MINUTES")
telegram_bind_code_max_failures: int = Field(default=5, alias="TELEGRAM_BIND_CODE_MAX_FAILURES")
```

`.env.example` 增加：

```env
# Telegram Bot integration
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
TELEGRAM_BOT_INTERNAL_TOKEN=replace-with-random-internal-token
TELEGRAM_BIND_CODE_TTL_MINUTES=10
TELEGRAM_BIND_CODE_MAX_FAILURES=5
WEB_INTERNAL_API_BASE=http://moyin-api:8000
```

生成内部 token：

```bash
openssl rand -base64 48
```

### 绑定码格式

建议：

```text
TG-ABCD-1234
```

实际存库只存 hash，不存明文 code。

Hash 函数建议确定性 HMAC：

```python
hmac.new(settings.jwt_secret.encode(), normalized_code.encode(), hashlib.sha256).hexdigest()
```

原因：要根据用户输入 code 快速查表；不能用随机盐密码 hash，否则无法索引查找。

### service 函数

```python
def create_bind_token(session: Session, user: PortalUser, settings: Settings) -> tuple[str, TelegramBindToken]:
    ...


def bind_telegram_user(
    session: Session,
    *,
    code: str,
    telegram_id: str,
    telegram_username: str | None,
    settings: Settings,
) -> PortalUser:
    ...


def unbind_telegram_user(session: Session, user: PortalUser) -> PortalUser:
    ...


def get_user_by_telegram_id(session: Session, telegram_id: str) -> PortalUser | None:
    ...
```

### 必须覆盖的规则

- code 大小写/短横线可宽松处理，但存储统一 normalized；
- code 10 分钟过期；
- code 一次性使用；
- 超过失败次数禁用；
- 同一个 `telegram_id` 只能绑定一个 Portal 用户；
- 同一个 Portal 用户已绑定时，默认拒绝生成新 code，除非先解绑；
- 绑定成功写：
  - `PortalUser.telegram_id`；
  - `PortalUser.telegram_username`；
  - `PortalUser.telegram_bound_at`；
  - `PortalUser.updated_at`；
  - `TelegramBindToken.used_at`；
  - `AuditLog(action="telegram.bind")`。

**验收：**

```bash
pytest tests/test_telegram_binding_service.py -q
pytest -q
```

---

## Phase 4：Web 用户接口：生成/解绑绑定码

**目标：** 登录 Web 账号中心后生成绑定码。

### 文件

Modify:

```text
backend/app/routers/me.py
backend/app/routers/auth.py
backend/tests/test_me_api.py
```

### API 设计

新增：

```http
POST /api/me/telegram/bind-token
DELETE /api/me/telegram/binding
```

返回示例：

```json
{
  "code": "TG-ABCD-1234",
  "expiresAt": "2026-07-11T11:30:00+00:00",
  "botUsername": "your_bot",
  "command": "/bind TG-ABCD-1234"
}
```

`DELETE` 返回：

```json
{
  "user": { ... },
  "ok": true
}
```

### `public_user()` 增加字段

当前 `public_user()` 只返回：

```json
id, username, role, status, expiresAt
```

增加：

```json
telegramBound: boolean
telegramUsername: string | null
telegramBoundAt: string | null
```

不要返回 `telegram_id`，避免把数字 ID 暴露给前端无必要展示。

### 测试

`backend/tests/test_me_api.py` 增加：

1. 登录用户可生成绑定码；
2. disabled/deleted 用户不能生成；
3. 已绑定用户生成 code 返回 409；
4. 解绑后 `telegram_id`、`telegram_username`、`telegram_bound_at` 清空；
5. 生成 code 不泄露 hash。

**验收：**

```bash
pytest tests/test_me_api.py -q
pytest -q
```

---

## Phase 5：Bot 内部 API

**目标：** 给 Bot 提供安全的内部接口。

### 文件

Create:

```text
backend/app/internal_auth.py
backend/app/routers/internal_tg.py
backend/tests/test_internal_tg_api.py
```

Modify:

```text
backend/app/main.py
backend/app/services/accounts.py  # 如果 Phase 6 抽服务时一起做
```

### 内部鉴权

`backend/app/internal_auth.py`：

```python
def require_internal_bot(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(Settings),
) -> None:
    expected = settings.telegram_bot_internal_token
    if not expected:
        raise HTTPException(status_code=503, detail="Telegram bot internal API is not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing internal token")
    token = authorization.split(" ", 1)[1]
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid internal token")
```

### API 设计

Router prefix：

```text
/api/internal/tg
```

Endpoints：

| Method | Path | 功能 |
|---|---|---|
| `POST` | `/bind` | 使用 Web 生成的 code 绑定 TG |
| `GET` | `/me/{telegram_id}` | 查询 TG 绑定账号和 ABS 状态 |
| `POST` | `/open` | 幂等开通/返回 ABS 账号状态 |
| `POST` | `/redeem` | 已绑定用户兑换续期码，复用现有 `redeem_code` 逻辑 |
| `GET` | `/library/summary/{telegram_id}` | 返回已绑定用户的库摘要 |
| `GET` | `/library/search/{telegram_id}?q=...&limit=...` | 搜索已绑定用户可见内容 |

### 返回用户状态

内部 API 用户对象应返回 Bot 可展示字段：

```json
{
  "bound": true,
  "user": {
    "id": "...",
    "username": "alice",
    "status": "active",
    "expiresAt": "...",
    "absUsername": "alice",
    "absUserId": "...",
    "telegramUsername": "..."
  },
  "serverUrl": "https://listen.moyin.cc"
}
```

注意：可以返回 `absUserId` 给 Bot 服务内部，但 Bot 回复给用户时通常不需要展示。

### `/open` 逻辑

第一版：

```python
if not bound:
    return 401/404 with "not_bound"
if user.status in {"disabled", "deleted"}:
    return 403
if user.abs_user_id:
    return {"opened": True, "alreadyOpen": True, ...}
else:
    # 进入补开号逻辑，见 Phase 6
```

### `/redeem` 逻辑

复用 `backend/app/routers/me.py::redeem` 的核心逻辑，建议抽到 service：

```text
backend/app/services/renewal.py
```

第一版也可以只支持 Web 续期，Bot 暂不做 `/redeem`；但如果要“打通流程”，建议加。

### 测试

`backend/tests/test_internal_tg_api.py`：

- 无内部 token → 401；
- 错 token → 403；
- 未配置 token → 503；
- `/bind` 成功写入用户；
- `/bind` 过期 code → 400；
- `/me/{telegram_id}` 未绑定 → `bound:false`；
- `/open` 对已有 `abs_user_id` 不创建新 ABS 用户；
- `/library/search` 未绑定 → 401/404；
- `/library/search` 结果截断 limit。

**验收：**

```bash
pytest tests/test_internal_tg_api.py -q
pytest -q
```

---

## Phase 6：抽统一账号 service，消除开号逻辑重复

**目标：** Web 注册、管理员创建、Bot 补开通共用同一套 ABS 创建/Portal 写入逻辑。

### 文件

Create:

```text
backend/app/services/accounts.py
backend/tests/test_account_service.py
```

Modify:

```text
backend/app/routers/auth.py
backend/app/routers/admin_users.py
backend/app/routers/internal_tg.py
```

### 为什么必须抽

现在 `auth.register` 和 `admin_users.create_user` 都直接：

```python
await abs_client.create_user(...)
PortalUser(...)
session.commit()
```

后续 Bot 再写一套会出现三套开号逻辑，风险高。统一 service 后：

```text
register route ─────┐
admin create route ─┼─> accountService.create_portal_user_with_abs(...)
bot open route ─────┘
```

### 建议 service API

```python
async def create_portal_user_with_abs(
    session: Session,
    *,
    username: str,
    password: str,
    email: str | None,
    duration_days: int,
    abs_factory: Callable[[], AudiobookshelfClient],
    actor: str,
) -> PortalUser:
    ...


async def ensure_abs_account_for_user(
    session: Session,
    *,
    user: PortalUser,
    password: str | None,
    abs_factory: Callable[[], AudiobookshelfClient],
) -> tuple[PortalUser, bool]:
    """Return user and created flag. If abs_user_id exists, created=False."""
```

### 关于缺失 `abs_user_id` 的处理

因为现有 Web 只保存 `password_hash`，无法还原用户密码给 ABS。因此如果一个 Portal 用户没有 `abs_user_id`：

第一版推荐：

- 不在 TG 中索要密码；
- 返回：`请先登录 Web 账号中心修改一次密码，然后再开通/修复媒体账号。`；
- 或在 Web 端提供“修复媒体账号”按钮，要求用户输入当前密码/新密码后创建 ABS。

如果你明确允许 Telegram 中输入密码，可以做，但不推荐。

### 测试

- 用户已有 `abs_user_id` 时 `ensure_abs_account_for_user` 不调用 ABS；
- 用户无 `abs_user_id` 且无 password 时返回明确错误；
- 用户无 `abs_user_id` 且有 password 时创建 ABS 并写回；
- ABS 创建成功但 DB commit 失败时尝试删除 ABS 用户，避免孤儿账号；
- duplicate username 仍被拒绝。

---

## Phase 7：Web Dashboard 增加 Telegram 绑定面板

**目标：** 用户在现有 `/dashboard` 中完成绑定码生成/解绑。

### 文件

Modify:

```text
web/lib/api.ts
web/app/dashboard/page.tsx
```

### `web/lib/api.ts` 变化

`PortalUser` 类型增加：

```ts
telegramBound?: boolean;
telegramUsername?: string | null;
telegramBoundAt?: string | null;
```

`api` 增加：

```ts
generateTelegramBindToken: () => request<{
  code: string;
  expiresAt: string;
  botUsername?: string | null;
  command: string;
}>('/api/me/telegram/bind-token', { method: 'POST' }),

unbindTelegram: () => request<{ ok: boolean; user: PortalUser }>(
  '/api/me/telegram/binding',
  { method: 'DELETE' }
),
```

错误翻译增加：

```ts
'Telegram account already bound': '当前账号已经绑定 Telegram，如需更换请先解绑。'
'Telegram bind token expired': '绑定码已过期，请重新生成。'
```

### Dashboard UI 放置位置

在 `web/app/dashboard/page.tsx` 的 `tab === 'account'` 内，建议放在“修改密码”模块前或后：

```text
账号状态
续期码
Telegram 绑定
修改密码
```

### 面板内容

未绑定：

- 标题：`绑定 Telegram Bot`
- 说明：`生成一次性绑定码后，在 Bot 中发送 /bind <code>`
- 按钮：`生成绑定码`
- 展示：code、过期时间、复制命令

已绑定：

- 显示：`已绑定 @username` 或 `已绑定 Telegram ID`
- 绑定时间；
- 按钮：`解绑 Telegram`。

### 前端验证

```bash
cd /root/audiobookshelf-portal/web
npm run lint
npm run build
```

---

## Phase 8：新增 Telegram Bot 服务

**目标：** Docker Compose 增加 `moyin-bot`，使用 polling 运行。

### 推荐语言

推荐 Python Bot，原因：

- 后端已经是 Python；
- 可以复用测试习惯和 Docker 基础镜像；
- 与 `moyin-api` 分服务运行，依旧只通过 HTTP API 通信。

### 文件

Create:

```text
bot/pyproject.toml
bot/Dockerfile
bot/app/__init__.py
bot/app/config.py
bot/app/internal_api.py
bot/app/handlers.py
bot/app/main.py
bot/tests/test_handlers.py
```

Modify:

```text
docker-compose.yml
.env.example
DEPLOYMENT.md
```

### `bot/pyproject.toml`

建议依赖：

```toml
[project]
name = "moyin-telegram-bot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "python-telegram-bot>=22",
  "httpx>=0.27",
  "pydantic-settings>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24"]
```

### Bot 命令

| 命令 | 行为 |
|---|---|
| `/start` | 欢迎；查询绑定状态；给出下一步 |
| `/help` | 命令说明 |
| `/bind <code>` | 调内部 API 完成绑定 |
| `/me` | 显示 Web/ABS 账号状态、有效期、服务地址 |
| `/open` | 幂等显示或开通 ABS 状态 |
| `/redeem <code>` | 可选：续期码兑换 |
| `/library` | 显示媒体库摘要 |
| `/search <关键词>` | 搜索当前可见作品 |
| `/latest` | 最近/预览内容 |

### Bot 回复文案示例

`/start` 未绑定：

```text
欢迎使用 MoYin.CC Bot。

你还没有绑定 Web 账号。
请先登录 https://moyin.cc/dashboard 生成 Telegram 绑定码，
然后在这里发送：
/bind TG-ABCD-1234
```

`/bind` 成功：

```text
绑定成功：alice
状态：正常
有效期：2026-08-10 12:00

之后可用 /me 查看账号，/library 查看媒体库。
```

`/open` 已开通：

```text
你的媒体账号已开通。
用户名：alice
服务地址：https://listen.moyin.cc
如果忘记密码，请到 Web 账号中心修改密码，会同步到听书 App。
```

### `docker-compose.yml` 增加

```yaml
  moyin-bot:
    build: ./bot
    container_name: moyin-bot
    restart: unless-stopped
    env_file: .env
    environment:
      WEB_INTERNAL_API_BASE: http://moyin-api:8000
    depends_on:
      - moyin-api
```

不需要对外暴露端口。

### Bot Dockerfile

```dockerfile
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir -e . \
    && useradd --create-home --uid 10002 botuser \
    && chown -R botuser:botuser /app
USER botuser
CMD ["python", "-m", "app.main"]
```

### Bot 测试

`bot/tests/test_handlers.py` 不需要真实 TG token，测试纯函数：

- `/bind` 无 code → 提示格式；
- `/bind` 成功 → 显示绑定成功；
- 内部 API 404 未绑定 → 显示先绑定；
- `/search` 超长结果 → 截断；
- 特殊 Markdown 字符 → 转义。

---

## Phase 9：ABS 数据给 Bot 使用

**目标：** Bot 查询 ABS 数据时遵守已有 Portal 权限和字段过滤。

### 复用/抽取现有逻辑

当前 `backend/app/routers/library.py::my_library_summary` 已做：

- 当前用户鉴权；
- 检查 disabled/deleted；
- ABS libraries；
- ABS user detail / progress；
- allowed libraries；
- sample items；
- public field projection。

建议把核心逻辑抽成：

```text
backend/app/services/library_summary.py
```

函数：

```python
async def build_library_summary_for_user(
    user: PortalUser,
    session: Session,
    abs_factory: Callable[[], AudiobookshelfClient],
) -> dict[str, Any]:
    ...
```

Then：

- Web `/api/library/summary` 调这个；
- Bot `/api/internal/tg/library/summary/{telegram_id}` 也调这个。

### 搜索实现

由于实测 ABS `/api/search` 404，第一版这样做：

1. 获取用户可见 libraries；
2. 每个 library 调 `list_library_items(library_id, limit=SEARCH_SCAN_LIMIT)`；
3. 用标题、作者、演播、路径字段做大小写包含过滤；
4. 返回前 `limit` 条；
5. 每条只包含公开字段：标题、作者、演播、时长、加入时间。

新增配置：

```python
telegram_search_scan_limit: int = Field(default=200, alias="TELEGRAM_SEARCH_SCAN_LIMIT")
telegram_search_result_limit: int = Field(default=8, alias="TELEGRAM_SEARCH_RESULT_LIMIT")
```

### 风险

如果库非常大，扫描会慢。第一版可接受，因为当前 ABS 只有 1 个库；后续再做：

- 本地缓存；
- 定时索引；
- SQLite FTS；
- 或找到 ABS 官方搜索 API 后替换。

---

## Phase 10：部署与验证

### 构建

```bash
cd /root/audiobookshelf-portal

docker compose build moyin-api moyin-web moyin-bot
```

如果 worker 也要重建：

```bash
docker compose --profile worker build moyin-worker
```

### 启动

```bash
docker compose up -d moyin-api moyin-web moyin-bot
```

当前 worker 本机已在跑，如需一起确保：

```bash
docker compose --profile worker up -d moyin-worker
```

### 健康检查

```bash
curl -fsS http://127.0.0.1:8019/api/public/health
curl -fsS http://127.0.0.1:8019/api/public/config
curl -fsS http://127.0.0.1:3009

docker compose logs --tail=100 moyin-api
docker compose logs --tail=100 moyin-web
docker compose logs --tail=100 moyin-bot
```

### 数据库迁移检查

```bash
docker exec moyin-api python -c "import sqlite3; c=sqlite3.connect('/data/portal.db'); print([r[1] for r in c.execute('pragma table_info(portal_users)')]); print(list(c.execute('pragma index_list(portal_users)')))"
```

应该能看到：

- `telegram_username`；
- `telegram_bound_at`；
- `ux_portal_users_telegram_id`。

### 手工验收流程

1. 登录 `https://moyin.cc/dashboard`。
2. 打开“Telegram 绑定”面板。
3. 点击生成绑定码。
4. 在 Bot 发送：

```text
/bind TG-ABCD-1234
```

5. Bot 返回绑定成功。
6. 再发：

```text
/me
/open
/library
/search 捞尸人
```

7. Web 端刷新后显示已绑定。
8. 数据库检查用户有 `telegram_id`，且没有明文绑定码。

---

## 4. 具体任务拆分

## Task 1：建立备份和测试基线

**Objective:** 在任何代码变更前保存 DB 和源码可回滚点。

**Files:** 无代码变更。

**Steps:**

1. 备份 `portal.db`。
2. 备份源码或初始化 git。
3. 跑后端 `pytest -q`。
4. 跑前端 `npm run lint`。

**Verification:** 备份文件存在，测试输出保存。

---

## Task 2：新增 SQLite migration 机制

**Objective:** 支持给现有库安全加 Telegram 字段/索引。

**Files:**

- Create: `backend/app/db_migrations.py`
- Create: `backend/tests/test_db_migrations.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/models.py`

**TDD:** 先写 `test_db_migrations.py`，确认没有 migration 时测试失败，再实现。

**Verification:**

```bash
pytest tests/test_db_migrations.py -q
pytest -q
```

---

## Task 3：实现 Telegram 绑定 service

**Objective:** 后端有可测试的绑定码生成/绑定/解绑逻辑。

**Files:**

- Create: `backend/app/services/telegram_binding.py`
- Create: `backend/tests/test_telegram_binding_service.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/models.py`

**TDD cases:**

- 生成 code；
- 成功绑定；
- 过期失败；
- 重复使用失败；
- 同一 TG 不能绑多个用户；
- 解绑成功；
- 审计日志写入。

---

## Task 4：实现 Web 端绑定码 API

**Objective:** 登录用户能生成绑定码和解绑。

**Files:**

- Modify: `backend/app/routers/me.py`
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/tests/test_me_api.py`

**Verification:**

```bash
pytest tests/test_me_api.py -q
pytest -q
```

---

## Task 5：实现 Bot 内部 API 鉴权和绑定接口

**Objective:** Bot 可安全调用后端绑定和查询用户。

**Files:**

- Create: `backend/app/internal_auth.py`
- Create: `backend/app/routers/internal_tg.py`
- Create: `backend/tests/test_internal_tg_api.py`
- Modify: `backend/app/main.py`

**Verification:**

```bash
pytest tests/test_internal_tg_api.py -q
pytest -q
```

---

## Task 6：抽账号 service，做 `/open` 幂等逻辑

**Objective:** 统一 Web 和 Bot 的开号逻辑，避免重复创建 ABS 用户。

**Files:**

- Create: `backend/app/services/accounts.py`
- Create: `backend/tests/test_account_service.py`
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/app/routers/admin_users.py`
- Modify: `backend/app/routers/internal_tg.py`

**Verification:**

```bash
pytest tests/test_account_service.py tests/test_auth_api.py tests/test_admin_users_api.py tests/test_internal_tg_api.py -q
pytest -q
```

---

## Task 7：抽 library summary service，给 Bot 搜索使用

**Objective:** Bot 可读取绑定用户可见库数据。

**Files:**

- Create: `backend/app/services/library_summary.py`
- Modify: `backend/app/routers/library.py`
- Modify: `backend/app/routers/internal_tg.py`
- Modify: `backend/tests/test_library_access_control.py`
- Create or modify: `backend/tests/test_internal_tg_library.py`

**Verification:**

```bash
pytest tests/test_library_access_control.py tests/test_internal_tg_library.py -q
pytest -q
```

---

## Task 8：Web Dashboard 增加 Telegram 绑定面板

**Objective:** 用户可以从 Web 账号中心生成绑定码。

**Files:**

- Modify: `web/lib/api.ts`
- Modify: `web/app/dashboard/page.tsx`

**Verification:**

```bash
cd web
npm run lint
npm run build
```

Manual：登录 `/dashboard`，生成绑定码，复制 `/bind ...` 命令。

---

## Task 9：新增 Bot 项目

**Objective:** `moyin-bot` 容器能启动并响应 TG 命令。

**Files:**

- Create: `bot/pyproject.toml`
- Create: `bot/Dockerfile`
- Create: `bot/app/config.py`
- Create: `bot/app/internal_api.py`
- Create: `bot/app/handlers.py`
- Create: `bot/app/main.py`
- Create: `bot/tests/test_handlers.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `DEPLOYMENT.md`

**Verification:**

```bash
cd bot
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q

cd ..
docker compose build moyin-bot
docker compose up -d moyin-bot
docker compose logs --tail=100 moyin-bot
```

---

## Task 10：端到端验收

**Objective:** 真实环境跑完整链路。

**Steps:**

1. 备份数据库。
2. 启动新版本 `moyin-api` / `moyin-web` / `moyin-bot`。
3. Web 生成绑定码。
4. TG Bot `/bind`。
5. TG Bot `/me`。
6. TG Bot `/open`。
7. TG Bot `/library`。
8. TG Bot `/search <关键词>`。
9. 检查日志和 DB。

**Success criteria:**

- 不泄露 token；
- 不重复创建 ABS 用户；
- Bot 未绑定用户不能读账号数据；
- disabled/deleted 用户不能通过 Bot 绕过限制；
- Web 和 Bot 显示的状态一致。

---

## 5. 安全要求

| 要求 | 实施方式 |
|---|---|
| 不在 TG 输入 Web 密码 | 只用 Web 登录态生成一次性绑定码 |
| Bot 内部 API 鉴权 | `TELEGRAM_BOT_INTERNAL_TOKEN` + constant-time compare |
| 绑定码不明文落库 | HMAC-SHA256 code hash |
| 防重复绑定 | `telegram_id` partial unique index |
| 防暴力猜码 | code TTL + failed_attempts + Bot rate limit |
| 敏感 env 不进 git | `.env` 已 ignore，继续只更新 `.env.example` |
| Bot 不持有 ABS token | Bot 只调用 `moyin-api` |
| 用户状态不绕过 | 内部 API 复用 `ensure_user_can_login` 和现有权限逻辑 |

---

## 6. 需要避免的坑

1. **不要只改 SQLModel 模型就以为 DB 更新了。** 当前没有 Alembic，必须写 SQLite migration。
2. **不要新建 `telegram_user_id` 字段。** 现有表已有 `telegram_id`，优先复用。
3. **不要让 Bot 直接访问 ABS admin token。** token 继续只在 `moyin-api`。
4. **不要在 Bot 中收用户密码。** 如需修复 ABS 账号，放 Web 端做。
5. **不要调用未验证的 ABS 搜索 API。** 本机实测 `/api/search` 为 404；第一版用 library items 过滤。
6. **不要重复创建 ABS 用户。** `/open` 必须先检查 `abs_user_id`。
7. **不要忘记 CSRF 中间件。** 内部 Bot API 没 cookie，可走 header token，不受 Web CSRF 影响；不要让它依赖 cookie。
8. **不要暴露 `moyin-bot` 端口。** polling 模式无需 inbound 端口。

---

## 7. 最终完成定义

- [ ] `/root/audiobookshelf-portal/.env.example` 包含 TG Bot 配置模板；
- [ ] DB 有 `telegram_bind_tokens` 表；
- [ ] `portal_users.telegram_id` 有 unique partial index；
- [ ] Web `/dashboard` 可生成绑定码；
- [ ] Web `/dashboard` 可解绑 Telegram；
- [ ] Bot `/bind` 可绑定已有 Web 账号；
- [ ] Bot `/me` 可查看账号状态；
- [ ] Bot `/open` 幂等，不重复创建 ABS 用户；
- [ ] Bot `/library` 可显示媒体库摘要；
- [ ] Bot `/search` 可搜索库内作品；
- [ ] 未绑定/禁用/删除用户不能通过 Bot 读取数据；
- [ ] 所有后端测试 `pytest -q` 通过；
- [ ] 前端 `npm run lint` 和 `npm run build` 通过；
- [ ] `docker compose up -d moyin-api moyin-web moyin-bot` 后服务正常；
- [ ] `docker compose logs moyin-bot` 无启动错误；
- [ ] 真实 TG Bot 端到端绑定成功。
