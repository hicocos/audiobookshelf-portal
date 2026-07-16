# Phase 4 PostgreSQL/Alembic 与 Redis 隔离演练

这套演练只验证未来迁移路径，不是生产迁移方案。`compose.phase4-lab.yml` 使用独立项目名、独立内部网络和独立命名卷，没有宿主端口，也不引用生产 `.env`、`moyin-data` 或 ABS 卷。所有服务都带 profile，因此默认执行 `docker compose -f compose.phase4-lab.yml up` 不会启动任何服务。

## PostgreSQL 与 Alembic

在仓库根目录运行：

```bash
docker compose -f compose.phase4-lab.yml --profile postgres-lab up \
  --build --abort-on-container-exit --exit-code-from phase4-alembic phase4-alembic
docker compose -f compose.phase4-lab.yml --profile postgres-lab run --rm \
  phase4-alembic uv run --frozen --no-sync alembic current
docker compose -f compose.phase4-lab.yml --profile postgres-lab down -v
```

预期 Alembic 升级到 `20260717_0001 (head)`。基线迁移是空 PostgreSQL 数据库的演练基线；现有生产 SQLite 仍继续由当前运行时代码管理，禁止把这里的 `DATABASE_URL` 或命令指向生产数据库。正式迁移前仍需单独验证类型、时区、唯一约束、外键删除行为、停机窗口和回滚。

## Redis

```bash
docker compose -f compose.phase4-lab.yml --profile redis-lab up \
  --abort-on-container-exit --exit-code-from phase4-redis-check phase4-redis-check
docker compose -f compose.phase4-lab.yml --profile redis-lab down -v
```

一次性检查容器会验证 `PING`、带 60 秒 TTL 的写读和删除。Portal/Bot 当前仍不依赖 Redis；此演练不改变会话、限流或任务队列实现。

## 隔离检查

```bash
docker compose -f compose.phase4-lab.yml --profile postgres-lab --profile redis-lab config
docker compose -f compose.phase4-lab.yml --profile postgres-lab --profile redis-lab ps
```

配置中不应出现 `ports:`、生产绝对路径、`moyin-data` 或生产服务名。演练结束始终执行对应的 `down -v`，只删除 `moyin-phase4-lab` 项目的演练卷。
