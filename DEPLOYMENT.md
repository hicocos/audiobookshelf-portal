# 生产部署与运行说明

## 服务

生产栈由 `/root/audiobookshelf-portal/docker-compose.yml` 管理：

- `audiobookshelf`：ABS 2.35.1，镜像按 digest 固定；仅监听宿主 `127.0.0.1:13268`。
- `moyin-api`：Portal API，仅监听 `127.0.0.1:8019`。
- `moyin-web`：Next.js，仅监听 `127.0.0.1:3009`。
- `moyin-bot`：Telegram polling，无宿主端口。
- `moyin-worker`：到期同步、群组宽限停用、通知和补偿任务；它是生产必需服务，默认启动。

所有容器运行时及用户可见时间统一为 `Asia/Shanghai`；API/Bot JSON 日志使用
`+08:00` 偏移。数据库与 API 传输仍以 UTC 保存，Web 和 Bot 在展示边界转换为上海时间。

Nginx 是唯一公网入口。ABS 通过 HTTPS 域名反向代理到 `127.0.0.1:13268`。

## 启动与更新

### 新机器首次部署

```bash
git clone <repository-url> /opt/audiobookshelf-portal
cd /opt/audiobookshelf-portal
./scripts/deploy.sh init
```

编辑生成的 `.env*`，至少替换 Portal 公网地址、ABS 管理 API token 和 Telegram Bot
token。默认 ABS 数据目录位于 `/srv/audiobookshelf/`，可在 `.env` 中修改四个
`ABS_*_PATH`。随后执行：

```bash
./scripts/deploy.sh check
./scripts/deploy.sh up
```

`init` 不覆盖已有配置；`check` 会拒绝占位值、非 `0600` 权限和无效 Compose 配置；
`up` 自动写入统一的构建版本、提交号和构建时间，构建并启动全部五个服务。

### 已有环境更新

```bash
cd /root/audiobookshelf-portal
./scripts/deploy.sh check
./scripts/deploy.sh up
```

Worker 不使用 Compose profile；默认命令必须同时检查并启动 Worker。

## 环境文件与权限

环境变量按服务隔离，均应为 `0600`，不得提交到 Git：

- `.env`：仅 Compose 插值（绑定地址、端口、Web 构建公开地址），不含秘密。
- `.env.api`：Portal API 的 JWT、数据库、ABS 管理 API key、内部 Bot 鉴权和 `TELEGRAM_ADMIN_IDS`。
- `.env.worker`：仅数据库、ABS URL、ABS 管理 API key。
- `.env.bot`：仅 Telegram Bot token、内部 API token、公开 URL和与 API 一致的 `TELEGRAM_ADMIN_IDS`。

模板位于 `deploy/env/`；`.env.example` 是完整变量索引，不应直接作为生产环境的单一
配置文件。首次部署默认密码最小长度为 12，已有部署保留当前显式配置。

`TELEGRAM_ADMIN_IDS` 使用逗号分隔的纯数字 Telegram ID。Bot 管理员必须同时将
Telegram 账号绑定到一个状态正常、角色为 `admin` 或 `root` 的 Portal 用户，单独配置
白名单不会获得管理权限。

若在后台开启“必需群组”，需将 Bot 提升为目标群组管理员，并确保 polling 接收
`chat_member` 更新。用户退群后进入配置的宽限期（默认 72 小时）；到期只停用账号，
不会删除账号，重新入群后仅自动恢复因退群而停用的账号。

检查变量名时不得输出变量值：

```bash
for n in moyin-api moyin-worker moyin-bot; do
  echo "[$n]"
  docker inspect "$n" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | cut -d= -f1 | sort
 done
```

## ABS 网络边界

预期监听：

```text
127.0.0.1:13268 -> audiobookshelf:80
```

验证：

```bash
ss -lntp | grep 13268
docker inspect audiobookshelf --format '{{json .NetworkSettings.Ports}}'
curl -fsS http://127.0.0.1:13268/ping
curl -fsS https://mp3.688606.xyz/ping
```

额外的 `DOCKER-USER` IPv4/IPv6 纵深防御规则由以下 systemd drop-in 在 Docker 启动后恢复：

```text
/etc/systemd/system/docker.service.d/20-abs-origin-port-guard.conf
```

检查：

```bash
iptables -S DOCKER-USER
ip6tables -S DOCKER-USER
systemctl show docker -p DropInPaths -p ExecStartPost
```

## ABS 管理凭据

Portal 使用 ABS 2.35.1 的托管 API key，而不是把 root 用户登录口令提供给 Portal。API key 名称为 `moyin-portal`，仅 API 与 Worker 持有。

轮换时：

1. 在 ABS 后台/API 创建新的启用 API key并绑定 root 管理用户。
2. 同时更新 `.env.api` 与 `.env.worker`。
3. 仅重建 API 与 Worker：

```bash
docker compose up -d --no-build moyin-api moyin-worker
```

4. 从 API 容器验证 `/api/me`、`/api/libraries` 返回 200。
5. 在 ABS 后台停用/删除旧 `moyin-portal` API key。

## 健康验证

```bash
docker compose config -q
docker compose ps
nginx -t
curl -fsS http://127.0.0.1:8019/api/public/health
curl -fsS http://127.0.0.1:3009/
curl -fsS http://127.0.0.1:13268/ping
curl -fsS https://mp3.688606.xyz/ping
```

ABS 应显示 `healthy`，并设置 `restart: unless-stopped`。

Range 验证：

```bash
curl -ksSI -H 'Range: bytes=0-15' https://mp3.688606.xyz/
```

预期：`206`，且存在 `Content-Range: bytes 0-15/...`。

## 回滚

本次网络、Compose 和密钥隔离改造前的回滚资料位于：

```text
/root/audiobookshelf-portal/.hermes/rollback/step1-20260716-223200/
```

旧手工 ABS 容器在新 Compose 服务验收通过后已删除。回滚时依据上述目录中的 `audiobookshelf.inspect.before.json` 重建旧参数；不要同时启动两个指向同一组可写挂载的 ABS 容器。

若新 ABS 无法启动：

1. 停止新的 `audiobookshelf` Compose 容器。
2. 依据回滚目录中的 inspect 文件及 `docker-compose.before.yml` 恢复原运行参数。
3. 恢复原 env/iptables 文件。
4. 验证 ABS `/ping`、Nginx、Range 和 WebSocket。
