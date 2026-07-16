# ABS 全栈审查问题五步整改计划

> **依据：** `/www/ABS-全栈-TelegramBot-Docker-全面审查报告-2026-07-15.md`  
> **执行原则：** 先保证数据可恢复，再收紧暴露面；先在测试/隔离环境验证，再进入生产维护窗口；每批变更均必须有备份、回滚方案和验收证据。  
> **第五步固定为：验收和收尾。**

**目标：** 用五个有明确顺序和门禁的步骤，处理报告中的 P0、P1、P2、P3 问题，使 ABS、Portal、Telegram Bot、Worker、Docker/Nginx 从“当前可用”达到“可恢复、边界清晰、稳定可运维、可持续迭代”。

**主要技术栈：** Next.js、FastAPI/SQLModel/SQLite（后续 PostgreSQL/Alembic）、python-telegram-bot、Docker Compose、Nginx、Cloudflare、restic/borg/rclone、pytest、Vitest/Playwright、Ruff/Bandit、Prometheus 或轻量监控方案。

---

## 总体顺序和完成门禁

| 步骤 | 建议周期 | 目标 | 完成门禁 |
|---|---:|---|---|
| 1. 数据保全与紧急止血 | 0–24 小时 | 避免不可恢复丢失，关闭最危险公网入口和密钥扩散 | 异机快照可恢复；13268 外网不可达；ABS 可自动恢复；各容器仅持有必要密钥 |
| 2. 账号、接口、Bot 与前端安全整改 | 1–3 天 | 修复身份、输入、会话、Bot、浏览器边界和高影响前端缺陷 | 弱密码/超长输入被拒；旧会话可撤销；bootstrap 不可抢占；Bot 私聊限定；安全头与动态 API 缓存策略通过 |
| 3. 数据一致性与容器运行时加固 | 3–10 天 | 消除 SQLite/多系统写入漂移，建立健康、资源、日志和故障恢复机制 | 并发与故障注入后状态收敛；容器 healthy；资源/日志限制生效；Worker 与 API 发布一致 |
| 4. 工程化、可观测性和中低优先级清理 | 1–6 周 | 建立可重复构建、测试、部署、监控和长期数据库/缓存架构 | Git/CI/锁文件/镜像固定完成；前端 E2E 覆盖关键路径；告警可触发；P2/P3 有关闭证据或明确延期批准 |
| 5. 验收和收尾 | 整改完成后，含 7 天观察期 | 统一回归、恢复演练、安全复测、文档移交和问题关闭 | 验收矩阵全绿；真实恢复成功；7 天无重大回归；遗留项有负责人和期限 |

> **依赖关系：** 步骤 1 未通过，不进入大规模代码/数据库改造；步骤 2、3 可按独立分支并行，但生产上线顺序仍须逐批执行；步骤 5 不是形式检查，任何 P0/P1 验收失败都必须退回对应步骤整改。

---

# 步骤一：数据保全与紧急止血（0–24 小时）

**覆盖问题：** P0-01；P1-01、P1-02、P1-03；并提前处理 P2-21、P2-03 的基础部分。

## 1.1 建立变更基线和回滚包

- [ ] 冻结非必要发布，记录当前容器、镜像、挂载、网络、端口、Nginx、Cloudflare 与数据库状态。
- [ ] 导出并加密保存：
  - `docker inspect audiobookshelf moyin-api moyin-web moyin-bot moyin-worker`
  - `/root/audiobookshelf-portal/docker-compose.yml`
  - `/www/server/panel/vhost/nginx/moyin.cc.conf`
  - `/www/server/panel/vhost/nginx/mp3.688606.xyz.conf`
  - ABS 对应 Nginx 配置、Cloudflare Cache Rules 截图/导出
  - 当前 `.env`，但必须单独加密，不能进入 Git 或普通备份包。
- [ ] 记录当前五个服务的镜像 ID/digest、启动参数、UID/GID、卷挂载和健康基线。
- [ ] 所有生产改动使用逐项变更单；每项写明“修改前证据、修改内容、验证、回滚命令”。

## 1.2 建立异机/离机备份

- [ ] 选择独立故障域：异机、NAS 或对象存储；不得把 RAID0 同机目录当作有效灾备。
- [ ] 使用 restic/borg/rclone 等支持增量、加密、校验和版本保留的工具。
- [ ] 首批必须覆盖：
  - `/www/wwwroot/audiobook/config/`
  - `/www/wwwroot/audiobook/metadata/`，可排除可再生的 `streams/`
  - `/var/lib/docker/volumes/audiobookshelf-portal_moyin-data/_data/portal.db`
  - `/root/audiobookshelf-portal/` 中源码和必要部署配置
  - 约 848GB 书库媒体文件
- [ ] SQLite 不允许直接复制活跃写入文件：
  - Portal DB 使用 `sqlite3 portal.db '.backup ...'` 或 SQLite backup API。
  - ABS DB 在可控停写窗口或用 SQLite backup API 创建一致性副本。
- [ ] 将散落在项目目录的明文 Portal DB 备份移入专用加密备份目录；目录权限设为 `0700`、文件 `0600`，定义保留期。
- [ ] 设定并书面确认：DB/配置 RPO ≤ 24 小时；书库按每日新增量或至少每周同步；明确 RTO。
- [ ] 配置每日自动任务、失败重试、备份新鲜度检查和 Telegram 告警。

## 1.3 立即做一次真实恢复演练

- [ ] 恢复到隔离目录/隔离主机，不覆盖生产。
- [ ] 对 Portal DB、ABS DB 执行 `PRAGMA quick_check;`，关键表做行数与抽样比对。
- [ ] 随机恢复至少 10 个媒体文件并对比 SHA-256；抽样需覆盖不同目录和不同大小。
- [ ] 验证 config、metadata、封面和源码配置可以重建服务。
- [ ] 保存恢复耗时、命令、错误、哈希和数据库检查输出，作为步骤 5 的验收证据。
- [ ] 中期制定 RAID0 迁移方案：RAID10/RAID6/ZFS mirror/RAIDZ2 或冗余 NAS；明确 RAID 不能替代备份。

## 1.4 关闭 ABS 公网直连端口 13268

- [ ] 先验证 Nginx 从本机/专用 Docker 网络可访问 ABS。
- [ ] 将端口改为 `127.0.0.1:13268:80`，或完全取消宿主端口，仅允许 Nginx/内部网络通过服务名访问。
- [ ] 在 `DOCKER-USER` 链显式拒绝公网到 13268，作为纵深防御；同时覆盖 IPv4/IPv6。
- [ ] 修改后验证：
  - `ss -lntp` 仅出现 `127.0.0.1:13268`，或不再出现宿主监听。
  - 从真正外部网络访问 `http://公网IP:13268` 必须超时或拒绝。
  - `https://listen.moyin.cc/ping` 返回 200。
  - 音频 Range 返回 206，WebSocket/Socket.IO 正常。

## 1.5 将 ABS 纳入可复现的 Compose 管理

- [ ] 把当前 ABS inspect 转换为受版本控制的 Compose 服务，准确保留 `/config`、`/metadata`、`/audiobooks` 挂载和网络。
- [ ] 暂时固定为已验证版本 `2.35.1`，随后补充 digest；禁止继续使用不受控的 `latest`。
- [ ] 设置 `restart: unless-stopped`；先添加最小健康检查，完整加固在步骤 3 完成。
- [ ] 在维护窗口重建并验证数据、权限、扫描、播放、封面、进度和客户端连接。
- [ ] 测试 Docker daemon 重启后 ABS 与 Portal 自动恢复。

## 1.6 拆分并旋转密钥

- [ ] 把公共 `.env` 拆成最小权限配置，建议路径：
  - `/root/audiobookshelf-portal/.env.api`
  - `/root/audiobookshelf-portal/.env.worker`
  - `/root/audiobookshelf-portal/.env.bot`
  - Web 仅使用明确的构建期公开变量
- [ ] 权限矩阵：
  - API：ABS admin token、JWT secret、DB URL、内部 Bot token。
  - Worker：ABS admin token、DB URL、必要业务设置。
  - Bot：Telegram Bot token、内部 API token、API base、Portal URL、welcome image URL。
  - Worker 不得拿 Telegram token；Bot 不得拿 ABS admin token、JWT secret、DB URL。
- [ ] 优先使用 Docker secrets/secret manager；如果暂时使用 env 文件，权限必须为 `0600`，且在 `.gitignore` 中。
- [ ] 拆分后依次旋转所有曾过度分发的密钥：ABS admin token、JWT secret、Telegram Bot token、内部 token；轮换时安排旧 token 的短暂双读/切换窗口，避免全服务同时中断。
- [ ] 用 `docker inspect` 验证各容器不再拥有无关密钥，但证据中只记录变量名，不输出秘密值。

## 步骤一完成标准

- [ ] 异机有 24 小时内可验证快照，且隔离恢复成功。
- [ ] 外网无法直连 13268，域名访问、206、WebSocket 正常。
- [ ] ABS 被 Compose 管理并配置自动重启。
- [ ] Bot/Worker 环境中不再存在无关高权限秘密，已完成密钥轮换。
- [ ] P0-01、P1-01、P1-02、P1-03 有证据包和回滚记录。

---

# 步骤二：账号、接口、Bot 与前端安全整改（1–3 天）

**覆盖问题：** P1-05、P1-06、P1-07、P1-09、P1-10、P1-12、P1-13、P1-14、P1-15、P1-16、P1-17；P2-08、P2-09、P2-10、P2-12、P2-13、P2-20、P2-22、P2-23；相关前端/Bot UX 缺陷。

## 2.1 提升密码、登录输入和请求边界

**主要文件：**
- `/root/audiobookshelf-portal/backend/app/config.py`
- `/root/audiobookshelf-portal/backend/app/routers/auth.py`
- `/root/audiobookshelf-portal/backend/app/routers/admin_bootstrap.py`
- `/root/audiobookshelf-portal/backend/app/rate_limit.py`
- `/root/audiobookshelf-portal/web/app/login/page.tsx`
- `/root/audiobookshelf-portal/web/app/register/page.tsx`
- 相关 backend tests 与 Nginx 配置

- [ ] 将普通用户密码最低长度提高到至少 10–12；管理员/bootstrap 至少 12。
- [ ] 保持对长密码/密码短语友好，但设置合理上限，例如 256 字符。
- [ ] Login username 限制 1–64/128，password 限制 1–256；所有长度检查必须在 PBKDF2 之前完成。
- [ ] Nginx/API 设置合理请求体上限，超大 JSON 快速拒绝。
- [ ] 注册、登录、bootstrap 在前后端使用一致规则；补充字段级错误、自动聚焦、`aria-live`、显示密码与 Caps Lock 提示。
- [ ] 现有弱密码用户采用渐进强制改密标志，不直接锁死全部账号。
- [ ] 评估 Argon2id 和哈希升级机制，但不得在未完成兼容测试时一次性迁移生产哈希。
- [ ] 登录、注册、bootstrap 分别按可信代理 IP、用户名、邀请码做限流；仅信任明确 Nginx 代理提供的真实 IP。
- [ ] 限流最终迁到 Redis/DB，避免多进程和重启后失效；短期至少保持后端边界二次限流。

## 2.2 增加会话撤销和角色一致性

**主要文件：** `backend/app/security.py`、`backend/app/auth_deps.py`、`backend/app/models.py`、`backend/app/session_cookie.py`、`backend/app/routers/me.py`、管理用户与改密路由。

- [ ] 为用户增加 `session_version` 或 `password_changed_at/revoked_at`；JWT 增加版本、`iat`，必要时增加 `jti`。
- [ ] 每次鉴权查询当前用户状态和会话版本；改密、停用、管理员强制下线、退出所有设备后旧 Cookie 立即 401。
- [ ] 缩短管理员会话有效期；高风险设置、用户/卡密操作要求近期重新认证。
- [ ] 增加“退出所有设备”，后续再扩展设备/会话列表。
- [ ] 用 Role Enum 和统一 `is_privileged_role()` 处理 `admin/root`；若业务不需要 `root`，删除该角色兼容分支。
- [ ] 为迁移补测试：旧 JWT、改密、停用、角色变化、并发登录、过期 token。

## 2.3 彻底关闭公开管理员抢占路径

**主要文件：** `web/app/admin/page.tsx`、`backend/app/routers/admin_bootstrap.py`、`backend/tests/test_admin_bootstrap_api.py`。

- [ ] 管理员登录失败只返回登录错误，不再自动 fallback 到 bootstrap。
- [ ] bootstrap 改为以下之一：本机 CLI、仅回环地址、一次性高熵 setup token；推荐 CLI 或一次性 token。
- [ ] 增加只读 setup status，但不得泄露敏感初始化状态细节。
- [ ] 初始化完成后永久禁用 bootstrap 路由或令 token 立即失效。
- [ ] 使用数据库事务/锁消除首次并发竞态，确保只能创建一个初始管理员。
- [ ] 验证空 DB 下匿名无 token 为 403；已初始化后错误登录只有一个 `/api/auth/login` 请求。

## 2.4 修复配置 API 和管理页覆盖风险

**主要文件：** `backend/app/routers/admin_settings.py`、`backend/app/services/settings.py`、`web/app/admin/config/page.tsx`、相关 tests。

- [ ] 用完整 Pydantic 嵌套模型替换 `dict[str, Any]`，只接受白名单字段。
- [ ] URL 默认只允许 `https` 和明确允许的相对路径；拒绝 `javascript:`、`data:`、异常 hostname/scheme。
- [ ] 限制 FAQ、timeline、步骤、公告、文本长度、数组数量和数值范围；错误类型返回 422。
- [ ] 前端使用统一 `hydrateSettingsForm()`；管理接口成功和公开配置降级分支都同步 `stepsText`、`faqText`、`timelineText` 等全部状态。
- [ ] 任一关键数据加载失败时禁用保存，或显示明确 diff 并要求确认。
- [ ] 增加配置版本历史/回滚；保存审计记录包含 before/after。
- [ ] 故障测试：管理接口 500、公开配置成功时，保存前后 FAQ/timeline/steps 不变。

## 2.5 修复 Dashboard 错误分类和前端 API 基础设施

**主要文件：** `web/lib/api.ts`、`web/app/dashboard/page.tsx`、Admin 相关页面。

- [ ] 定义带 `status`、`code`、`cause`、request ID 的 `ApiError`。
- [ ] fetch 增加 AbortController、超时、组件卸载取消；仅对安全 GET 做有限重试。
- [ ] 只在 401/403 跳转登录；500、超时、断网留在当前页面，显示可重试错误。
- [ ] `loadAll()` 使用 `try/finally` 保证 loading/busy 状态复位。
- [ ] 对关键 API 响应加入 Zod/Valibot 等运行时 schema 校验，避免畸形配置触发 `.trim()` 崩溃。
- [ ] 所有 Clipboard、刷新和按钮事件补 `catch/finally`，避免静默失败或永久 busy。
- [ ] 分别模拟 401、403、500、连接拒绝、超时与畸形 JSON。

## 2.6 加固 Telegram Bot

**主要文件：** `bot/app/main.py`、`bot/app/handlers.py`、`bot/app/internal_api.py`、`bot/tests/test_handlers.py`，以及后端 Telegram 绑定服务。

- [ ] 所有业务 handler 最前面强制 `ChatType.PRIVATE`；群组只回复“请私聊 Bot”，不解析、不记录、不回显邀请码/绑定码。
- [ ] 如果业务不需要群组，在 BotFather 禁止加入群组。
- [ ] 注册全局 error handler；生成 update/request ID，记录脱敏结构化错误，给用户统一短提示。
- [ ] 前置中间件/装饰器统一执行：私聊校验、每用户/每聊天限流、超时、幂等、防重复 callback。
- [ ] 限流覆盖 `/start`、`/help`、`/me`、`/open`、`/library`、`/search`、注册/绑定、文本菜单和 callback；后端边界再次限流。
- [ ] `allowed_updates` 仅保留 `message`、`callback_query` 等必要类型。
- [ ] 修复无效绑定码逻辑：随机无效码不得给所有开放 token 增加失败次数；按 TG ID/IP/提交者限流，只对匹配 token 记录失败。
- [ ] 生成新绑定码时撤销同用户旧码；定时清理过期/已用 token，保留审计摘要。
- [ ] 不再永久发送初始密码：使用 60 秒一次性领取链接，或发送后自动删除；完整验证前不要删除现有流程。
- [ ] 增加 `/cancel` 和会话超时清理；清理内存中的邀请码；删除“签到”死入口、`-z` 异常文案和未使用键盘代码。
- [ ] 模拟内部 API 断网、500、Telegram 429、重复 callback、群组误用和流程超时。

## 2.7 浏览器响应头和 Cloudflare 缓存边界

**主要文件：** `/www/server/panel/vhost/nginx/moyin.cc.conf`、ABS 域名 Nginx 配置、`web/next.config.*`、Cloudflare Cache Rules。

- [ ] 抽取统一 Nginx 安全头 include，避免 `location` 内 `add_header` 覆盖 server 级 HSTS。
- [ ] 基线包含：HSTS、`X-Content-Type-Options: nosniff`、`Referrer-Policy`、`Permissions-Policy`、`frame-ancestors 'none'` 或 X-Frame-Options DENY。
- [ ] CSP 先用 Report-Only 收集违规，再逐步切换 enforce；不能直接上线可能阻断 Next.js/ABS 资源的策略。
- [ ] Next.js 设置 `poweredByHeader: false`。
- [ ] Cloudflare 对 `/api/*`、登录、Socket.IO、用户数据一律 Bypass；源站动态响应设置 `private, no-store`，必要时正确设置 `Vary`。
- [ ] 音频 Range 缓存单独配置，验证 206 和 `Content-Range`。
- [ ] 清理 Nginx 中 TLSv1.1、3DES/旧 RSA 套件声明，保留现代 TLS1.2/1.3 配置。

## 步骤二完成标准

- [ ] 低于阈值密码、257 字符密码、超大 JSON、非法 URL/配置均在昂贵操作前快速拒绝。
- [ ] 改密、停用、退出所有设备后旧 Cookie 立即 401。
- [ ] 未授权 bootstrap 不可用且无并发抢占。
- [ ] Dashboard 对 5xx/断网不再误跳登录；Admin 降级加载不会覆盖配置。
- [ ] Bot 群聊不解析敏感码；所有命令有限流和全局错误处理。
- [ ] 门户/ABS 安全头通过；动态 API 始终 `DYNAMIC/BYPASS`，不同用户响应不串号。

---

# 步骤三：数据一致性与容器运行时加固（3–10 天）

**覆盖问题：** P1-04、P1-08、P1-11；P2-01、P2-04、P2-05、P2-11、P2-14、P2-15、P2-16、P2-19；后端 N+1、连接复用、Worker 多副本风险。

## 3.1 修正 SQLite 初始化和并发模型

**主要文件：** `backend/app/db.py`、`backend/app/main.py`、`backend/app/worker.py`、`backend/app/db_migrations.py`、`backend/app/models.py`、相关 tests。

- [ ] 将 engine 改为进程级单例；普通请求不得重复 `create_db_and_tables()` 或 `run_migrations()`。
- [ ] 仅在应用 lifespan/startup 运行初始化和版本检查；迁移失败直接阻止 readiness，而不是影响普通请求路径。
- [ ] SQLite 启用 WAL、`foreign_keys=ON` 和合理 `busy_timeout`；确认所有连接都应用 PRAGMA。
- [ ] 统一事务边界；仅对可安全重试的锁冲突做有界退避重试。
- [ ] 新增 `username_normalized = casefold(username)` 与唯一索引；`abs_username` 同样规范化；捕获约束冲突返回 409。
- [ ] 完善缺失外键和迁移；上线前先扫描孤儿记录，禁止直接新增约束导致迁移失败。
- [ ] 压测并发注册、续期、Worker 巡检和大小写用户名竞态，确保无 `database is locked` 和重复账号。

## 3.2 用 Outbox/Saga 消除 Portal 与 ABS 状态漂移

**主要文件：** 注册、续期、管理用户、`backend/app/services/codes.py`、`backend/app/abs_client.py`、`backend/app/worker.py`、新增 migration/model/tests。

- [ ] 为“创建 ABS 用户、续期恢复、停用/删除、批量恢复”定义明确状态机和幂等键。
- [ ] 本地事务同时写业务状态和 outbox 任务；后台 Worker 执行 ABS 写入并记录 attempts、next_retry_at、last_error、最终状态。
- [ ] 补偿失败不能再 `except Exception: pass`；写入 reconciliation/failed_jobs 并告警。
- [ ] 对 ABS 请求使用幂等检查：创建前查重、更新前比较目标状态、删除前确认映射。
- [ ] 实现状态对账任务：识别“ABS 有、Portal 无”“Portal 有、ABS 无”“续期已消费但 ABS 未恢复”等情况。
- [ ] 提供管理员只读失败队列、一键重试/修复和完整审计；高风险修复要求确认。
- [ ] 故障注入：ABS 超时、DB commit 失败、Worker 中断、重复投递、批量处理中断；最终必须自动或经明确人工动作收敛，无静默孤儿账号。

## 3.3 添加真实健康检查和发布依赖

- [ ] API 拆分 `/health/live` 与 `/health/ready`：readiness 检查 DB `SELECT 1`、迁移版本和必要的 ABS 连通性。
- [ ] Worker 暴露/写入 `last_success`、`last_error`、lag；超过阈值判定不健康并告警。
- [ ] Web healthcheck 检查服务端页面/内部 API 可用性；Bot healthcheck 检查进程和最近 polling 状态，但避免频繁调用 Telegram。
- [ ] Compose `depends_on` 使用 `condition: service_healthy`，避免只等待容器启动。
- [ ] `docker ps` 必须显示 healthy；故意让 API 不健康时验证 Bot/Web 行为和恢复路径。

## 3.4 Docker 运行时加固

**主要文件：** `/root/audiobookshelf-portal/docker-compose.yml`、各 Dockerfile。

- [ ] 所有服务配置 `restart: unless-stopped`、`init: true`、合理 `stop_grace_period`。
- [ ] 日志统一 `json-file` 轮转，例如 `max-size: 10m`、`max-file: 5`，Nginx 同时确认 logrotate。
- [ ] 按压测结果设置 memory、CPU、PID 限制和 reservation；不得凭空设置过小值导致生产抖动。
- [ ] Portal 容器使用 `read_only: true`、必要 `tmpfs`、`cap_drop: [ALL]`、`no-new-privileges:true`。
- [ ] ABS 先在测试环境验证明确 UID/GID、能力裁剪、非 root 兼容性；若不需修改源媒体，将 `/audiobooks` 改为只读。
- [ ] Worker 从可选 profile 中移除，或把生产命令固定为 `docker compose --profile worker up -d` 并在部署脚本中校验。
- [ ] API/Worker 使用同一构建产物和镜像 digest，消除源码漂移。
- [ ] 统一时区为 `Asia/Shanghai` 或 UTC，保证宿主、ABS、Portal、日志时间一致。

## 3.5 清理 ABS 数据与临时流问题

- [ ] 清理前备份 ABS DB。
- [ ] 根据日志中的缺失 file/item ID 核对目录，在 ABS 管理界面对相应库执行 scan/清理缺失项。
- [ ] 对已删除 item 的失效进度先导出再清理；保留审计记录。
- [ ] 检查 stream cleanup 配置；对停止播放流设置 TTL，清理 174k 小文件的异常长流。
- [ ] `streams/` 不纳入高频核心备份，但监控目录大小、文件数和最长存活时间。
- [ ] 清理后连续观察媒体索引错误、invalid socket token、stream 大小趋势，目标为错误显著下降并无新增孤儿项。

## 3.6 后端性能和审计补齐

- [ ] ABS client 改为应用级共享 HTTP client/连接池，统一超时、重试、request ID 和关闭流程。
- [ ] 管理 overview 消除串行 N+1，采用批量接口或受控并发，并设置上限。
- [ ] Bot 搜索优先使用 ABS 搜索 API/索引，不再每次扫描每库 500 项。
- [ ] 统一审计 schema：actor ID/name、IP、request ID、before/after、结果、失败原因。
- [ ] 覆盖改密、续期、登录失败、设置修改、卡密状态/删除、bootstrap 和对账修复。
- [ ] 修复 `actor_username` 错写成用户 ID；定义审计保留和防篡改策略。
- [ ] 高价值卡密评估改为 HMAC/hash 存储和最后四位展示；恢复旧快照时旧卡密应自动失效。

## 步骤三完成标准

- [ ] 请求路径不再执行 DDL/迁移；WAL、foreign key、busy timeout 生效。
- [ ] 并发注册/续期/Worker 压测无锁错误，大小写变体只能一个成功。
- [ ] ABS/DB 故障注入后 outbox 可重试并最终收敛，无静默孤儿账号。
- [ ] 所有容器 healthy，重启策略、资源限制、日志轮转和安全选项可从 inspect 验证。
- [ ] API/Worker 镜像 digest 一致；Worker 默认生产部署不会遗漏。
- [ ] ABS 索引错误与 streams 异常已清理并进入持续监控。

---

# 步骤四：工程化、可观测性和中低优先级清理（1–6 周）

**覆盖问题：** P2-02、P2-03、P2-06、P2-07、P2-17、P2-18、P2-24，以及全部 P3；完成 PostgreSQL/Alembic、Redis、监控告警和长期存储迁移准备。

## 4.1 建立 Git、分支、CI 和可重复构建

- [ ] 在确认 `.env`、数据库、备份、媒体文件已被 `.gitignore` 排除后初始化 Git，并推送私有远程仓库。
- [ ] 使用 main/release/tag 流程；生产镜像标注 Git SHA、构建时间、迁移版本。
- [ ] Backend/Bot 使用 uv 生成并提交锁文件；固定传递依赖。
- [ ] Python/Node/ABS 基础镜像固定版本与 digest；由 Renovate/Dependabot 发起受控升级。
- [ ] CI 顺序：
  1. Backend/Bot pytest
  2. Ruff
  3. Bandit
  4. pip-audit
  5. TypeScript
  6. Next production build
  7. npm audit
  8. Vitest/React Testing Library
  9. Playwright smoke
  10. Compose config、镜像构建、SBOM/漏洞扫描
- [ ] 清理 Ruff 8 个错误、Bandit 5 个 Low 和 5 个弃用警告；补规则后将新增问题设为 CI 阻断。
- [ ] Next.js 从 16.2.7 升级到已验证 patch 版本前，必须通过完整 CI/E2E。

## 4.2 补齐自动化测试

- [ ] Web 建立 Vitest + React Testing Library，至少覆盖：ApiError 翻译、安全 redirect、登录/注册校验、Dashboard loading、Admin 配置 hydrate、Modal/tab 状态。
- [ ] Playwright 覆盖首页、登录、注册、用户中心、续期、管理登录/配置保存、错误状态和移动端弹窗。
- [ ] Bot 使用模拟 Update/Context/InternalApi 覆盖私聊、群拒绝、429、超时、流程过期、重复 callback、全局错误处理。
- [ ] 后端增加并发、迁移、outbox、会话撤销、配置 schema、大小写唯一性和 trusted proxy 限流测试。
- [ ] 建立发布前 smoke：门户 200、API ready、Bot `getMe`/内部 API、ABS ping、Range 206、WebSocket。

## 4.3 拆分大型前端并修复无障碍/体验问题

- [ ] 将 `web/app/admin/config/page.tsx` 和 `web/app/dashboard/page.tsx` 拆成 domain hooks、schema、表单、tab、modal 与展示组件。
- [ ] 使用 query/cache 层统一 loading、error、retry、取消和缓存，不再让大型页面自行管理全部状态。
- [ ] 修复 `<a><button>` 嵌套；Button 支持 `asChild` 或 Link 使用按钮样式。
- [ ] Modal 使用原生 `<dialog>` 或成熟组件，支持 `role=dialog`、`aria-modal`、焦点陷阱/恢复、Escape、body scroll lock。
- [ ] 修正文案双问号、`-z`、重复入口和技术化描述；公告联系方式改为可点击/可复制且有失败提示。
- [ ] 检查复杂背景上的文字对比度；使用 axe-core 和键盘导航验收。
- [ ] 增加 `error.tsx`、`loading.tsx`、`global-error.tsx`、`not-found.tsx`，为 dashboard/admin 提供品牌化错误和重试。

## 4.4 优化缓存、静态资源和目录卫生

- [ ] HTML/鉴权页面保留 `no-store`；`/_next/static/` 改为 `public, max-age=31536000, immutable`。
- [ ] 图片/字体按版本化策略缓存；动态 API 继续禁止公共缓存。
- [ ] 清理 `web/public` 中约 61.6MB 未引用图片；生成素材移到归档/对象存储，实际资源转 WebP/AVIF。
- [ ] CI 增加静态资源引用检查和体积预算。
- [ ] 将 `backups`、`_web_backups_archive`、构建产物、node_modules 从源码备份范围分离并设置保留期。
- [ ] 在无构建任务的维护窗口清理约 23.2GB Docker build cache，并记录清理前后磁盘变化。
- [ ] 清理不再解析的 `demo.moyin.cc` Nginx 配置及证书维护项，操作前确认无业务依赖。

## 4.5 可观测性与告警

- [ ] 统一结构化 JSON 日志、request/update ID、敏感字段脱敏；Portal、Bot、Worker、ABS 调用可串联查询。
- [ ] 采集 HTTP 延迟/错误、ABS 调用、DB 锁、outbox backlog、Worker lag、备份新鲜度、streams 文件数、磁盘/RAID/SMART。
- [ ] 使用 Prometheus/Grafana/Loki，或轻量 Uptime Kuma + node_exporter + cAdvisor；工具可简化，但指标不能省略。
- [ ] Telegram 告警覆盖：备份失败、恢复校验失败、Worker 超时、ABS 5xx、磁盘阈值、SMART/RAID、证书临期、outbox 积压。
- [ ] 告警必须有去重、恢复通知、责任人和运行手册，避免告警风暴。

## 4.6 长期架构迁移

- [ ] 在完成 SQLite 稳定化后制定 PostgreSQL + Alembic 迁移：双重备份、schema、数据校验、停写窗口、回滚、主键/时间/唯一性兼容。
- [ ] 迁移演练至少两次；比较表行数、关键聚合、抽样记录和业务回归后才切生产。
- [ ] Redis 用于分布式限流、Bot flow persistence、幂等键和 Worker 分布式锁；Redis 故障时要有明确降级策略。
- [ ] 制定 RAID0 到冗余存储的迁移窗口；完成全量同步、增量追平、只读切换、抽样哈希和回滚。
- [ ] 建立自动化部署：build once、测试、DB backup、migrate、健康检查、原子替换、失败回滚。

## 步骤四完成标准

- [ ] 所有构建由锁文件和固定 digest 可重复产生，CI 全绿后才能发布。
- [ ] Web/Bot/Backend 的关键缺陷有自动化回归测试。
- [ ] P2/P3 清单逐项有“已修复证据”或经批准的延期记录，不能静默遗留。
- [ ] 监控能真实触发并送达告警，且恢复通知有效。
- [ ] PostgreSQL、Redis、冗余存储和自动部署至少完成隔离环境演练；生产迁移有独立变更单。

---

# 步骤五：验收和收尾

**目标：** 不以“代码已合并/容器已启动”为完成，而以恢复能力、安全边界、故障收敛、功能回归和持续观察均通过为准。

## 5.1 建立问题—修复—证据矩阵

- [ ] 以报告中的 P0-01、P1-01～P1-17、P2-01～P2-24、P3-01～P3-10 建立台账。
- [ ] 每项至少记录：负责人、修改文件/配置、测试、生产验证、证据路径、回滚方法、完成时间。
- [ ] P0/P1 必须全部关闭；若确实无法完成，需书面风险接受、补偿控制、负责人和最迟期限。
- [ ] P2/P3 不允许仅标“以后处理”，必须是已完成、明确延期或不适用，并附理由。

## 5.2 灾难恢复最终验收

- [ ] 从异机最新备份恢复 Portal DB、ABS DB/config、metadata 和随机 10 个媒体文件到隔离环境。
- [ ] 两个 SQLite/PostgreSQL 数据库执行完整性检查和关键业务数据比对。
- [ ] 媒体 SHA-256 全部一致；ABS 能索引并播放抽样媒体。
- [ ] 记录实际 RPO、RTO，并与目标比较；不达标则回到步骤 1/4。
- [ ] 自动备份连续成功运行至少 7 天；模拟一次备份失败，确认 Telegram 告警送达。

## 5.3 安全与边界验收

- [ ] 从外网验证 13268 不可达，只有 HTTPS 域名入口有效。
- [ ] 检查 Bot/Worker/API 环境变量最小权限，不输出秘密值。
- [ ] 验证 HSTS、CSP、frame、nosniff、Referrer、Permissions-Policy；确认 CSP 无业务误拦截。
- [ ] 使用两个不同用户验证 `/api/*` 不被 Cloudflare 共享缓存，不发生响应串号。
- [ ] 验证弱密码、超长输入、超大请求、恶意 URL、非法配置被拒。
- [ ] 验证改密、停用、退出所有设备后旧 Cookie 立即失效。
- [ ] 验证匿名 bootstrap 403，群组 Bot 不解析敏感码，全部 Bot 路径限流有效。
- [ ] 复跑 CORS、CSRF、未授权后台/API、Range 206、WebSocket 测试。

## 5.4 稳定性、一致性与回归验收

- [ ] Backend、Bot、Web 单元/集成/E2E、类型检查、生产构建、依赖审计全部通过。
- [ ] 复跑 Ruff、Bandit、pip-audit、npm audit；新增问题为 0，允许遗留项必须有批准记录。
- [ ] 并发注册、续期、Worker 巡检无 `database is locked`。
- [ ] 注入 ABS 超时、DB commit 失败、Worker 中断、网络 500/429；outbox 最终收敛，用户得到明确提示，无静默孤儿账号。
- [ ] Docker daemon 重启后五个服务自动恢复并显示 healthy。
- [ ] 验证 memory/CPU/PID 限制和日志轮转；确认没有因限制过低导致 OOM/重启循环。
- [ ] 清理 ABS 索引/streams 后观察错误趋势，确认无持续增长。
- [ ] 桌面端和移动端回归：首页、登录、注册、Dashboard、续期、管理配置、Bot 绑定/注册、ABS 播放。

## 5.5 7 天观察期

- [ ] 观察 Portal 4xx/5xx、登录失败、Bot error handler、Worker lag、outbox backlog、ABS 错误、SQLite/PostgreSQL 锁、CPU/内存、磁盘/streams、备份新鲜度。
- [ ] 每日检查告警与异常趋势；P0/P1 回归立即回滚或修复，不等待观察期结束。
- [ ] 观察期内不得混入无关大功能发布，保证问题可归因。
- [ ] 连续 7 天无重大回归、备份连续成功、关键指标稳定后才正式关闭整改项目。

## 5.6 文档、移交与关闭

- [ ] 更新部署文档：统一 Compose、Worker 启动方式、镜像 digest、密钥分配、健康检查、发布和回滚。
- [ ] 更新运维手册：备份/恢复、密钥轮换、用户/ABS 对账、outbox 失败处理、RAID/SMART/磁盘告警。
- [ ] 更新安全手册：管理员初始化、会话撤销、Bot 私聊规则、Cloudflare/Nginx 基线。
- [ ] 将恢复演练、外网端口测试、响应头、CI、E2E、故障注入和 7 天监控截图/日志归档到只读证据目录。
- [ ] 清除临时测试 token、测试账号、恢复目录和明文调试数据；确认生产秘密未进入 Git、日志、截图或工单。
- [ ] 生成最终关闭报告，列出：已关闭问题、延期项、已知限制、下次恢复演练日期、下一次密钥轮换日期、负责人。

## 最终验收判定

只有同时满足以下条件，整改才可标记为完成：

1. **P0 全部关闭，P1 全部关闭或有正式风险接受。**
2. **异机备份可真实恢复，且自动任务连续 7 天成功。**
3. **13268 公网不可达，密钥最小权限、会话撤销和 Bot 私聊限制均生效。**
4. **故障注入后数据最终一致，无静默孤儿账号。**
5. **容器自动恢复且 healthy，CI/E2E/安全复测全绿。**
6. **文档、证据、回滚、负责人和后续日期完整。**

---

## 建议的实施批次

为降低一次性改动风险，建议生产发布拆成以下批次，每批单独验证和回滚：

1. **批次 A：** 备份/恢复、13268、ABS Compose/restart、密钥拆分与轮换。
2. **批次 B：** 密码/输入限制、bootstrap、会话撤销、限流。
3. **批次 C：** Dashboard/Admin 前端缺陷、Bot 私聊/error handler、配置 schema、安全头/Cloudflare。
4. **批次 D：** SQLite 生命周期/WAL/外键、Outbox/Saga、healthcheck、运行时加固。
5. **批次 E：** CI/测试/监控、前端重构、缓存/资源清理、PostgreSQL/Redis/冗余存储迁移。
6. **最终批次：** 统一验收、7 天观察、文档移交和关闭报告。
