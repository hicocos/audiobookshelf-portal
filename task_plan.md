# ABS Portal 审查计划

目标：审查自写 audiobookshelf-portal（moyin-api/moyin-web/moyin-worker）的前端、后端、业务逻辑、安全漏洞与优化建议。

## 阶段

- [x] 定位项目与运行组件
- [ ] 梳理项目结构、配置、容器与入口
- [ ] 后端 API/认证/授权/数据库/业务逻辑审查
- [ ] 前端页面/接口调用/状态和输入处理审查
- [ ] 运行测试、构建和静态扫描验证
- [ ] 输出分级报告与修复优先级

## 范围

- 项目目录：`/root/audiobookshelf-portal`
- 容器：`moyin-api`, `moyin-web`, `moyin-worker`
- 官方 ABS 容器 `audiobookshelf` 不作为主要审查对象，只审查 portal 与 ABS 集成逻辑。
