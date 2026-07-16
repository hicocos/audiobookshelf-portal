# ABS 第五步验收与收尾报告（2026-07-17）

> 验收时间：2026-07-17 06:51 CST。
>
> 本报告执行五步计划中的第五步，但遵守用户确定的范围：**RAID、业务数据备份/恢复、SMART、冗余存储不处理；密码最低长度保持 3，延期处理。** 因此“整改项目全部关闭”和“7 天观察期完成”当前不能宣称完成，本次结论为“技术验收通过，进入观察期，范围排除项和延期项保留”。

## 1. 第四步最终确认

- 已生成 `.hermes/step4-remediation-evidence-2026-07-17.md`。
- 最终构建注入已提交 Git revision `13585bfc8b40`。
- API/Worker 同一运行镜像 digest：`sha256:4d124fc2e8433f0d95ef1f504b662807e2291995330dd3076cf0682f33074547`。
- Bot digest：`sha256:c7264ef1810d1e1d4f3607bcba176cc14d3b71eeb2314a1dc74a8c42ef9165cb`。
- Web digest：`sha256:e3867db637a2897620ec361a7af5fcc95d3ad24d813101382d53ea85a693d99a`。
- 最终发布版本标签为 `phase4-final`；Phase 4 四个服务重建后均 healthy；ABS 亦 healthy。

## 2. 自动化质量门禁

| 项目 | 结果 |
|---|---|
| Backend pytest | 146 passed |
| Backend Ruff | 通过 |
| Backend/Bot Bandit | 0 issue |
| Backend pip-audit | 无已知漏洞；仅本地项目包不在 PyPI，按预期跳过 |
| Bot pytest | 17 passed |
| Bot Ruff | 通过 |
| Web Vitest/RTL | 4 files / 17 passed |
| TypeScript | 通过 |
| Next production build | 通过 |
| Playwright | 7 passed / 1 skipped（desktop 项目跳过 mobile-only overflow 断言） |
| npm audit | 0 vulnerabilities |
| Compose 主配置/实验配置 | 通过 |
| Nginx config | 通过并已 reload |
| public 资产检查 | 1 个实际资源 / 1,747,678 bytes，预算通过 |

说明：一次从项目根目录运行 Backend pytest 导致归档目录同名测试和 Bot 依赖被错误收集；随后按各组件工作目录及各自 venv 正确重跑，以上为纠正后的有效结果。

## 3. 运行时、网络和媒体验收

- `audiobookshelf`、`moyin-api`、`moyin-worker`、`moyin-bot`、`moyin-web`：running/healthy，RestartCount=0，OOMKilled=false。
- 资源使用远低于限制：ABS 约 100 MiB/2 GiB；API 约 65 MiB/512 MiB；Worker 约 49 MiB/512 MiB；Bot 约 41 MiB/384 MiB；Web 约 63 MiB/512 MiB。
- 所有服务 json-file 日志轮转为 10m×5。
- ABS 端口仅 `127.0.0.1:13268` 监听；IPv4/IPv6 `DOCKER-USER` 拒绝外部原始 13268。
- Portal 200；API ready 200；ABS ping 200。
- `listen.moyin.cc` 与 `mp3.688606.xyz` Range 请求均返回 206，`Content-Range: bytes 0-31/4136`。
- Socket.IO polling 返回 200 且声明 websocket upgrade；实际 WebSocket Upgrade 返回 `101 Switching Protocols`。

## 4. 安全边界验收

- 公网 Portal `/`、`/login`、`/admin`：HSTS、CSP、DENY frame、nosniff、Referrer-Policy、Permissions-Policy 生效，未见 X-Powered-By。
- Portal 动态 API：`private, no-store`、`cf-cache-status: DYNAMIC`；匿名 `/api/me` 与 `/api/admin/users` 均 401。
- 公网 `/metrics` 为 404；宿主 localhost 匿名访问同样为 404。指标端点现为 fail-closed，只有配置 `METRICS_TOKEN` 并携带 Bearer token 的监控采集器才可读取。
- 独立代码审查发现并已修复 request-ID 的未处理异常路径：安全 500 响应携带 `X-Request-ID`，观测/日志异常不会掩盖业务异常，ContextVar 在独立最外层 `finally` 复位；新增回归测试后 Backend 为 148 passed。
- 最终 API/Worker 热修复发布版本 `phase5-final`，revision `35acdf4f1787`，二者 healthy 且使用同一镜像。
- CORS 恶意 Origin 预检为 400；伪 Cookie 且无 Origin/Referer 的写请求为 403。
- 已初始化实例匿名 bootstrap 返回 409（路由关闭状态）；257 字符登录密码在哈希前返回 422。
- 密码最低长度复读为 3，证明本轮没有误改延期项。
- Bot 环境无 ABS admin/JWT/DB；Worker 环境无 Telegram Bot/internal token。
- 未发现 Phase 5 临时用户、临时审计 actor 或临时恢复目录。

## 5. 数据一致性和可观测性验收

- Portal SQLite `quick_check=ok`、WAL。
- 应用实际连接：`foreign_keys=1`、`busy_timeout=10000`。
- reconciliation pending/retry/failed 合计 0。
- 用户名规范化空值 0、大小写规范化碰撞 0。
- `X-Request-ID: phase5-probe-20260717` 在响应和 JSON 日志中一致。
- Metrics：database/audiobookshelf ready=1、reconciliation backlog 全 0、Worker lag 正常。
- 最近 6 小时 Worker/Web/ABS 无 ERROR；Bot 出现 1 次 Telegram `Bad Gateway` 网络错误，已由全局错误处理器捕获并恢复，容器持续 healthy，不是崩溃或业务数据错误。

## 6. 第五步问题—结论矩阵

| 范围 | 结论 | 证据/说明 |
|---|---|---|
| P1 网络端口、Compose、自恢复 | 已关闭 | localhost 13268、DOCKER-USER、五服务 healthy |
| P1 密钥最小权限 | 已关闭 | 运行容器变量名负向检查 |
| P1 SQLite 生命周期/一致性 | 已关闭（SQLite 阶段） | WAL/FK/busy timeout、并发测试、reconciliation=0 |
| P1 会话、bootstrap、输入、设置、Bot、安全头 | 已关闭 | 自动化测试与线上探针 |
| P2/P3 工程化、测试、资源、缓存、无障碍 | 主要关闭 | CI/lock/tests/assets/Modal/错误边界；见延期项 |
| PostgreSQL/Redis | 隔离演练就绪，生产延期 | `compose.phase4-lab.yml`、`backend/PHASE4_LAB.md` |
| Git remote | 延期 | 本机 Git 已建立，未提供私有 remote/凭据 |
| Next patch 升级 | 延期 | 保持 16.2.7，需独立 CI/E2E 变更 |
| 大页面全面拆分 | 延期 | 关键纯逻辑/Modal 已抽取，领域组件继续重构 |
| 长期监控栈/告警路由 | 部分完成 | metrics/JSON/health 已有；Prometheus/Grafana/Loki 和正式告警未部署 |
| 密码最低长度 | 用户批准延期 | 当前 3，未修改 |
| RAID/备份/SMART/冗余存储 | 用户排除 | 不纳入完成判定，不重复整改 |

## 7. 本次额外修复

第五步发现 Nginx 通用 `location /` 的 no-store 覆盖了 Next 静态资源 immutable。已增加专用 `location ^~ /_next/static/`、隐藏上游 Cache-Control 并统一输出 immutable；Nginx 测试和 reload 成功。公网复测只剩一条：

`Cache-Control: public, max-age=31536000, immutable`

## 8. 当前判定

### 已通过

- 第四步技术门禁全部完成。
- 第五步即时回归、安全边界、运行时、媒体协议、数据一致性、测试/构建/扫描验收通过。
- 未留下生产测试账号或临时恢复数据。

### 尚不能宣布“整改项目最终关闭”

1. 五步计划要求的 7 天观察期尚未经过；观察期从本次最终重建验收后开始。
2. 用户排除的 RAID/备份/恢复项不纳入本轮执行，因此原报告 P0-01 只能标记为“范围外、用户自行规划”，不能写成技术已修复。
3. 密码最低长度为用户批准延期。
4. 长期监控/正式告警栈、Git remote、Next patch、PostgreSQL/Redis 生产迁移和大页面进一步拆分有明确延期记录。

**阶段结论：第五步即时验收通过，进入 7 天观察期；不是最终关闭。**
