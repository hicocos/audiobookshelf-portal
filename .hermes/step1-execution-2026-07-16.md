# 步骤一整改执行记录（排除 RAID 与备份）

- **执行时间：** 2026-07-16（Asia/Shanghai）
- **执行范围：** 用户明确要求不处理三盘 RAID0 的影响，且备份由用户另行规划。因此本记录仅覆盖公网端口、ABS Compose/自动恢复、服务密钥隔离与轮换、运行验证。

## 已完成

### 1. ABS 公网源站端口收口

- ABS 宿主映射从 `0.0.0.0/[::]:13268` 改为 `127.0.0.1:13268`。
- IPv4/IPv6 `DOCKER-USER` 增加 13268 拒绝规则，作为未来误发布端口时的纵深防御。
- systemd drop-in `/etc/systemd/system/docker.service.d/20-abs-origin-port-guard.conf` 用于 Docker 启动后恢复规则。
- 验证 `ss` 仅显示 `127.0.0.1:13268`。

### 2. ABS 纳入 Compose

- `audiobookshelf` 已写入 `/root/audiobookshelf-portal/docker-compose.yml`。
- 镜像按 digest 固定：ABS 2.35.1 对应已验证 digest。
- 设置 `restart: unless-stopped`。
- 增加 `/ping` healthcheck，当前状态 `healthy`。
- 保留原 `/config`、`/metadata`、`/audiobooks`、`/podcasts` 挂载。
- 时区从 `America/Toronto` 统一为 `Asia/Shanghai`。
- 已删除迁移过程中保留的旧手工 ABS 容器，当前只有一个 ABS 容器。

### 3. 环境变量最小权限拆分

- 根 `.env` 只保留 Compose 插值，不再包含秘密。
- `.env.api`：API 所需 JWT、DB、ABS 管理 API key、内部 Bot 鉴权等。
- `.env.worker`：仅 ABS URL、ABS 管理 API key、DB URL。
- `.env.bot`：仅 Telegram Bot token、内部 API token、API base、Portal URL、welcome image URL。
- 四个 env 文件均为 `0600`。
- 验证 Bot 不再含 ABS token/JWT/DB；Worker 不再含 JWT/Telegram token。

### 4. 密钥轮换

- Portal `JWT_SECRET` 已轮换；旧 Portal Cookie 因此失效，用户需重新登录。
- Bot 与 API 之间的内部 bearer token 已轮换。
- ABS 侧已创建专用、可管理、可停用的 `moyin-portal` API key，并只分发给 API 与 Worker。
- Telegram Bot token 未轮换：Bot 已在轮换后隔离为仅 Bot 持有，若通过 BotFather 轮换将造成外部凭据变更，需单独安排。

## 验证结果

| 项目 | 结果 |
|---|---|
| Backend pytest | 116 passed，5 warnings |
| Bot pytest | 12 passed |
| Web TypeScript | 通过 |
| Compose config | 通过 |
| Nginx config | 通过 |
| ABS 容器 | running、healthy |
| ABS restart policy | unless-stopped |
| ABS 监听 | 仅 `127.0.0.1:13268` |
| Portal API | HTTP 200 |
| Portal Web | HTTP 200 |
| ABS 本机 `/ping` | HTTP 200 |
| `mp3.688606.xyz/ping` | HTTP 200 |
| `listen.moyin.cc/ping` | HTTP 200 |
| Range | 两个 ABS 域名均返回 206 与正确 Content-Range |
| WebSocket | 两个 ABS 域名 `/socket.io` 均返回 101 Switching Protocols |
| ABS 管理 API key | `/api/me`、`/api/libraries` 均返回 200 |
| Bot polling | getUpdates 正常 |
| Worker | 当前 tick 成功，无错误 |

## 文件变更

- `/root/audiobookshelf-portal/docker-compose.yml`
- `/root/audiobookshelf-portal/.env`
- `/root/audiobookshelf-portal/.env.api`
- `/root/audiobookshelf-portal/.env.worker`
- `/root/audiobookshelf-portal/.env.bot`
- `/root/audiobookshelf-portal/DEPLOYMENT.md`
- `/etc/systemd/system/docker.service.d/20-abs-origin-port-guard.conf`

## 回滚证据

```text
/root/audiobookshelf-portal/.hermes/rollback/step1-20260716-223200/
```

包含修改前 Compose、环境文件、ABS/Portal inspect 和 iptables/ip6tables 规则。秘密文件权限为 `0600`，目录权限为 `0700`。

## 明确未做

- 未处理 RAID0、磁盘阵列或备份方案，遵循用户要求。
- 未轮换 Telegram BotFather token；已完成最小权限隔离。
- 未重启 Docker daemon；通过 Compose/inspect、restart policy、healthcheck 和 systemd drop-in 加载结果完成非破坏性验证。完整 daemon restart 可在后续维护窗口执行。
