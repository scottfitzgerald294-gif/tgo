# 阶段3实施计划：开发治理与项目骨架复验

## 基线

- 起点分支：`pdd-customer-service`
- 起点提交：`85ac181750cd92e6af3b814bab83a66f52f5d66f`
- 执行分支：`phase/03-governance`
- 既有完成标签：`phase-03-complete`
- 初始工作区：干净

阶段3的代码骨架、健康检查、测试、局部开发规范和依赖锁已在既有提交中完成。本次不重复实现，只补齐无人值守执行要求并重新验收。

## 目标

1. 补齐周末执行计划和阶段报告目录。
2. 补齐扩展顶层 `fixtures/` 占位目录。
3. 在根 `docs/runbooks/` 提供开发入口，链接扩展的权威运行手册。
4. 重新执行健康检查、格式、类型、测试和安全验收。
5. 确认 `.env`、密钥、日志、缓存和本地数据库不会被跟踪。
6. 确认阶段3没有修改 `repos/*` 核心业务。

## 明确不做

- 不重复实现健康接口。
- 不接入真实拼多多、TGO业务API、模型、数据库或消息系统。
- 不修改根 `.gitignore`，除非验收证明现有规则失效。
- 不移动或覆盖既有 `phase-03-complete` 标签。
- 不修改或合并 `main`、`master` 或上游稳定分支。

## 预计创建或修改的文件

- 新增 `docs/weekend-run/phase-03-plan.md`
- 新增 `docs/weekend-run/phase-03-report.md`
- 新增 `docs/weekend-run/logs/phase-03-validation.md`
- 新增 `docs/runbooks/development.md`
- 新增 `extensions/pdd-customer-service/fixtures/.gitkeep`

预计不修改任何既有生产代码。

## 验证命令

从 `extensions/pdd-customer-service/` 执行：

```bash
make format
make lint
make test-unit
make test-integration
make test
make security-check
```

附加检查：

```bash
git check-ignore -v extensions/pdd-customer-service/.env
git diff --name-only phase-02-complete..HEAD -- repos
git diff --check
git status --short
```

只有全部自动检查通过，阶段3才记为 `PASS` 并进入阶段4。
