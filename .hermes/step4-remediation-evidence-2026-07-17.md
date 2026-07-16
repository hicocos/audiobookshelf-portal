# ABS 第四步整改实施与验收证据（2026-07-17）

> 范围：工程化、自动化测试、前端可维护性/无障碍、静态资源、可观测性、隔离架构演练和可重复构建。
>
> 明确排除：RAID、业务数据备份/恢复、SMART、冗余存储迁移；密码最低长度保持 3，留待后期单独处理。

## 已实施

### Git、CI 与可重复构建

- 初始化 Git `main` 分支并建立源码基线。
- `.gitignore` 排除 `.env*`、数据库、回滚包、归档、Node/Python 生成物。
- Backend/Bot 生成并提交 `uv.lock`；Dockerfile 使用 `uv sync --frozen`。
- Python、uv 与 ABS 镜像固定 digest；Compose 支持 OCI version/revision/created 构建标签。
- 新增 `.github/workflows/ci.yml`：pytest、Ruff、Bandit、pip-audit、Web tests/build/audit、Playwright、Compose、SBOM 与 Trivy。

### 自动化测试和前端

- Web 建立 Vitest + React Testing Library 与 Playwright 桌面/移动端 smoke。
- 抽取 `AccessibleModal`：`role=dialog`、`aria-modal`、Escape、焦点圈定/恢复、body scroll lock。
- 增加 `error.tsx`、`loading.tsx`、`global-error.tsx`、`not-found.tsx`。
- 抽取安全 redirect 与管理配置 hydrate 纯逻辑并覆盖测试。
- 修复首页嵌套交互。
- 管理页完成关键共享逻辑抽取，但大型页面的全面领域组件拆分延期到后续常规重构，不作为生产安全阻断项。

### 静态资源和缓存

- 将未引用生成素材移出 `web/public` 到 `/www/abs-web-unused-assets-2026-07-17/`。
- 生产 public 只保留实际使用背景，约 1.75 MB。
- 新增 `scripts/check_public_assets.py` 作为引用和体积预算门禁。
- Nginx 为 `/_next/static/` 设置唯一 `public, max-age=31536000, immutable`，HTML/鉴权页面保持 no-store。

### 可观测性

- API/Bot 使用 JSON 日志；API 回显和记录受限格式的 `X-Request-ID`。
- 新增 `/metrics`：HTTP count/latency、DB/ABS readiness、reconciliation backlog、Worker lag、build info。
- `/metrics` 仅宿主 localhost 可访问，公网 `https://moyin.cc/metrics` 返回 404。
- 新增发布 smoke 脚本。

### 长期架构隔离演练

- 新增 Alembic scaffold、PostgreSQL/Redis 依赖组、`compose.phase4-lab.yml` 和 `backend/PHASE4_LAB.md`。
- 实验 Compose 不挂载生产卷、不复用生产端口，默认不随生产 Compose 启动。
- 未执行生产 PostgreSQL/Redis 迁移。

## 实际验收结果

- Backend：146 passed；Ruff 通过；Bandit 0 issue；pip-audit 无已知漏洞。
- Bot：17 passed；Ruff 通过；Bandit 0 issue。
- Web：Vitest 17 passed；TypeScript 通过；Next production build 通过；Playwright 7 passed / 1 desktop-only mobile assertion skipped；npm audit 0 vulnerabilities。
- Compose 主配置和实验配置通过。
- 五个服务均 running/healthy、RestartCount=0、OOMKilled=false。
- API/Worker 运行同一镜像 digest；运行时 read-only、资源/PID 限制、日志 10m×5 生效。
- Portal 200、API ready 200、ABS ping 200。
- Range：`listen.moyin.cc` 与 `mp3.688606.xyz` 均为 206，含 Content-Range。
- Socket.IO/WebSocket：polling 200 且返回 websocket upgrade；真实 Upgrade 返回 101。
- Portal DB：quick_check=ok、WAL；应用连接 foreign_keys=1、busy_timeout=10000；reconciliation open=0；规范化用户名空值/碰撞=0。
- Request ID：指定 `phase5-probe-20260717` 被响应头和 JSON 日志正确关联。
- Metrics：DB/ABS ready=1、reconciliation backlog 全 0、Worker lag 正常。
- Bot/Worker 不含不必要的高权限环境变量名。
- 静态缓存：`/_next/static/*` 仅返回 immutable；HTML no-store。

## 已知遗留与延期

1. 未配置私有 Git remote，无法推送远程；本机 Git 与 CI 文件已就绪。
2. Next.js 仍为 16.2.7；patch 升级延期到独立变更，需复跑 CI/E2E。
3. PostgreSQL/Redis 仅隔离演练 scaffold，生产迁移需独立停写和回滚变更单。
4. 管理/Dashboard 大页面仍需进一步领域组件拆分。
5. Prometheus 指标已实现，但长期 Prometheus/Grafana/Loki/Uptime Kuma 服务栈与告警路由尚未部署；当前依靠 Docker health、JSON 日志和现有 Telegram Bot 基础。
6. 密码最低长度保持 3（用户明确延期）。
7. RAID、备份、SMART、冗余存储均不在本次范围。
