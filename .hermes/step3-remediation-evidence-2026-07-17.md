# ABS 整改步骤三实施记录（2026-07-17）

> 范围：数据一致性与容器运行时加固。用户明确要求用户名保持不区分大小写；本次通过规范化列和数据库唯一索引强化该行为，没有改为区分大小写。
>
> 不在范围：RAID 与备份方案。本记录中的源码回滚包只用于本次代码/Compose 变更回滚，不代表业务数据备份。

## 已实施

### 3.1 SQLite 初始化与并发

- `backend/app/db.py`
  - 进程级 Engine 单例。
  - 请求依赖不再建表或跑迁移。
  - SQLite 每个连接启用 WAL、`foreign_keys=ON`、`busy_timeout=10000`、`synchronous=NORMAL`。
- `backend/app/main.py`
  - 只在应用 lifespan startup 建表/跑迁移；失败会阻止应用 ready。
- `backend/app/worker.py`
  - Worker 只在进程启动时初始化数据库，普通 tick 不再跑 DDL/迁移。
- `backend/app/models.py` / `backend/app/db_migrations.py`
  - 新增 `username_normalized` 与 `abs_username_normalized`。
  - 使用 Python `casefold()` 回填并建立唯一索引。
  - 迁移先检测碰撞；发现碰撞直接失败，不静默覆盖。
  - 用户名业务语义仍为**不区分大小写**。

### 3.2 一致性与对账

- 新增 `reconciliation_jobs` 表和 `backend/app/services/reconciliation.py`。
- 续期已本地提交但 ABS 恢复失败时，持久化幂等重试任务；Worker 有界指数退避处理。
- 新增管理员只读队列：`GET /api/admin/users/reconciliation`。
- 新增管理员重置失败任务：`POST /api/admin/users/reconciliation/{job_id}/retry`。
- Telegram 注册补偿删除失败不再静默吞掉，改为带 ABS user ID 的错误日志。

### 3.3 健康检查

- API：`/api/public/health/live` 与 `/api/public/health/ready`。
  - readiness 验证 DB `SELECT 1` 与 ABS `/ping`。
- Worker：持久化 last success/error/result 到只读容器的 tmpfs，并由 Docker healthcheck 检查新鲜度。
- Web：容器内请求 Next 服务。
- Bot：容器内检查 API liveness，避免频繁调用 Telegram。
- ABS：保留 `/ping` healthcheck。

### 3.4 Docker 运行时

- 所有服务：`restart: unless-stopped`、`init: true`、stop grace、Asia/Shanghai、json-file 10m×5。
- API/Worker/Web/Bot：read-only rootfs、tmpfs、drop ALL capabilities、no-new-privileges。
- API/Worker：同一镜像 `audiobookshelf-portal-backend:step3`，运行 digest 相同。
- Worker 从 profile 移除，默认 Compose 部署包含 Worker。
- 资源限制依据部署前空闲快照设置并留有余量：
  - ABS 2 GiB / 2 CPU / 256 PIDs
  - API、Worker、Web 各 512 MiB / 1 CPU / 128 PIDs
  - Bot 384 MiB / 0.75 CPU / 96 PIDs
- ABS 保持兼容性优先：未强制只读书库、非 root 或 drop ALL；已启用 no-new-privileges、资源和日志限制。

### 3.5 ABS 索引与 streams

- 只读检查显示当前 `metadata/streams` 为 0 文件。
- 重建后最近日志未发现新的 `Library file ... does not exist`、`Library item not found` 或 ERROR。
- 因当前无待清理对象，未执行破坏性数据库/索引清理。

### 3.6 性能

- ABS HTTP client 支持共享连接池、拆分 connect timeout 和连接上限。
- Bot 搜索改用已在生产只读探针确认的 `/api/libraries/{id}/search?q=...`，不再每库扫描 500 条。
- 管理用户列表已使用一次 ABS `list_users` 批量合并；管理 library overview 的 per-user detail 仍按数据需要调用，后续可继续做受控并发优化。

## 验收证据

- Backend：`140 passed`（另有 6 个既有弃用 warning）。
- Bot：`15 passed`。
- Web：TypeScript 与 Next production build 通过。
- Bandit：0 issue。
- Compose config：通过。
- Portal DB：`quick_check=ok`、`journal_mode=wal`、63 用户、规范化空值 0、大小写碰撞 0。
- SQLite API 连接：`foreign_keys=1`、`busy_timeout=10000`。
- 并发大小写注册测试：仅一个成功，另一个唯一约束冲突；无 `database is locked`。
- API/Worker 镜像 digest 相同。
- 公网：Portal 200、ABS ping 200、Range 206，`Content-Range` 正常。
- 所有带 healthcheck 的容器应显示 healthy，Worker last-success healthcheck 也纳入 Compose。

## 回滚

- 源码/Compose 回滚包：`/root/audiobookshelf-portal-step3-rollback-20260716-234106.tar.gz`
- SHA-256：`eea59db4d4e12576c97dc1ee4cbb98a53eed844dfb9317c370d18cab1bb106a8`
- 权限：`0600`

注意：SQLite 新增规范化列、索引、WAL 与 `reconciliation_jobs` 是向前兼容 schema。直接回滚旧镜像前，应先确认旧代码可忽略新增列/表；不要删除生产列或表作为常规回滚动作。
