# 拼多多客服扩展开发入口

权威开发运行手册位于：

- `extensions/pdd-customer-service/docs/runbooks/development.md`

所有扩展开发命令必须从 `extensions/pdd-customer-service/` 执行：

```bash
make format
make lint
make test
make test-unit
make test-integration
make security-check
```

阶段3只包含项目骨架和无外部依赖的健康检查。真实拼多多、真实模型、生产数据和TGO核心业务修改均未获授权。
