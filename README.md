# Audiobookshelf Portal

Twilight-inspired self-service account portal for Audiobookshelf.

P0–P3 的实现和上线状态见 [`ROADMAP.md`](./ROADMAP.md)。

## Quick start

新机器只需要 Docker、Docker Compose v2、Git 和 OpenSSL。初始化脚本会生成四份
权限为 `0600` 的服务隔离配置，并自动创建 JWT、内部 API、指标和管理员初始化密钥：

```bash
git clone <repository-url> audiobookshelf-portal
cd audiobookshelf-portal
./scripts/deploy.sh init
# 编辑 .env* 中的域名、ABS API token 和 Telegram Bot token
./scripts/deploy.sh check
./scripts/deploy.sh up
```

可在初始化时传入非敏感和敏感配置，减少手工编辑：

```bash
PORTAL_PUBLIC_URL_INIT=https://portal.example.com \
ABS_ADMIN_TOKEN='...' \
TELEGRAM_BOT_TOKEN='...' \
TELEGRAM_BOT_USERNAME='my_bot' \
./scripts/deploy.sh init
```

脚本不会覆盖任何已有环境文件。完整的反向代理、存储和运行说明见
[`DEPLOYMENT.md`](./DEPLOYMENT.md)。

## Telegram Bot account lifecycle

The Bot supports invite-based account creation, binding an existing portal account,
renewal-code preview/confirmation, recent listening, announcements, client setup
help, and one-time password-reset links. Registration and renewal conversations are
stored in the portal database, so a Bot restart does not lose an active flow.

For bound regular users, `/start` shows at most two recent listening entries and
offers library search. The existing media-request flow is unchanged; its entry
prompt reminds users that current audiobook processing targets Ximalaya FM and asks
them to include the title, narrator, and current episode count.

All service runtimes, logs, Bot messages, and Web date displays use
`Asia/Shanghai`. Database timestamps and API transport values remain UTC internally
and are converted at the display boundary.

The background worker queues account-expiry reminders in a durable outbox.
The Bot claims and acknowledges those messages, with retry/backoff for transient
Telegram failures. Feature switches and reminder timing are available in the admin
configuration page.

The P2/P3 feature set adds a Telegram admin console, media-request tickets,
required-group enforcement with a 72-hour grace period, daily check-in, an immutable
points ledger, expiry-day redemption, limited single-use referral invites, and an
anonymous opt-in leaderboard. Destructive user actions require a preview/confirm
step and are written to the audit log; the Bot never deletes portal or ABS users.
Registration and renewal codes are generated and managed only in the Web admin
console. The Telegram admin console can reply directly to media-request tickets and
handle common account expiry/status actions. Bulk account management and expiry
compensation also remain in the Web admin console.
The Web console also provides an opt-in anonymous leaderboard and an audited
broadcast workflow with audience preview, recipient-count confirmation, durable
queueing, and delivery retry.

Telegram administrators are deliberately protected by two checks: their Telegram ID
must be listed in `TELEGRAM_ADMIN_IDS`, and that Telegram account must be bound to an
active Portal user with the `admin` or `root` role. Group enforcement also requires
the Bot to be an administrator in the configured Telegram group so it can inspect
members and receive `chat_member` updates.

完整变量索引在 `.env.example`，可直接部署的分服务模板位于 `deploy/env/`。Keep
`TELEGRAM_BOT_INTERNAL_TOKEN` identical in the API and Bot environments, and use a
long random value because the `/api/internal/tg` routes can mutate user accounts.
Set the same comma-separated `TELEGRAM_ADMIN_IDS` value in the API and Bot
environments. P2/P3 switches and reward values are configured under the Telegram
section of `/admin/config`.

## Backend dev

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]' respx
pytest -q
```

## Bot dev

```bash
cd bot
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```
