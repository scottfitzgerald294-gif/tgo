# 阶段6报告：消息可靠性机制

## 结论

阶段6自动验收为`PASS`。本阶段只在
`extensions/pdd-customer-service/`增加本地SQLite可靠性机制，没有调用真实
拼多多、真实TGO业务API、真实模型、生产数据或付费服务。

- 分支：`phase/06-message-reliability`
- 设计提交：`e91287d`
- 计划提交：`a27c930`
- 阶段最终提交：由`phase-06-complete^{commit}`唯一解析
- 阶段标签：`phase-06-complete`
- 主分支合并、Pull Request和强制推送：0

## 已实现范围

数据流：

```text
FAKE/TEST请求
→ 时间窗口校验
→ SQLite Inbox/Outbox原子Claim
→ 重复短路
→ 完整会话锁
→ AI/human reply lease
→ Mock入站与会话关联
→ 超时、重试、死信
→ 持久审计
→ 自动回复或安全失败
```

实现内容：

- `shop_id + message_id`本地模拟唯一键和原子去重；
- 五种持久状态：`pending/sent/failed/retrying/dead_letter`；
- 默认3次尝试、指数退避和发送超时；
- Mock前N次失败、入站幂等和`reply_id`出站幂等；
- 同一完整会话串行、不同会话并行；
- AI/human owner与单调epoch，发送前二次核对；
- 取消后保留现场、同一SQLite文件重启恢复；
- Claim及处理中途数据库故障的脱敏安全失败；
- 201、409、503和持久GET FastAPI行为；
- schema v1、运行手册、单元与集成测试。

## 明确未实现

- 真实PDD URL、字段、签名、nonce、加密、应答、幂等Header或错误码；
- 真实TGO API、RAG、模型、生产数据库或分布式消息队列；
- 多Connector副本、分布式锁或生产级数据库迁移；
- 自动死信重放、真实人工工作台或阶段8完整会话状态机；
- 真实店铺授权、真实买家数据和生产自动回复。

本地`shop_id + message_id`只用于模拟验收，不能冒充真实拼多多合同。

## TDD与故障证据

所有行为先观察RED，再写最小GREEN。完整逐项证据见
[`logs/phase-06-validation.md`](logs/phase-06-validation.md)。

关键RED包括：

- 模型、SQLite仓库、可靠服务和API注入点尚不存在；
- 10次重复被重复记录；
- 第3次失败仍向上抛出而非进入死信；
- 悬挂发送由外部测试护栏取消；
- 同会话第二条在首条释放前进入发送；
- human接管后旧AI epoch仍成功发送；
- 取消旧任务后新服务缺少恢复入口；
- 数据库故障直接泄漏底层异常；
- 应用工厂不接受可靠性账本。

调试均遵守最多两轮根因分析。本阶段没有通过删除测试、降低断言、关闭安全检查
或硬编码成功结果绕过失败。

最终自动化结果：

| 检查 | 结果 |
|---|---|
| 单元测试 | 36项通过 |
| 集成测试 | 7项通过 |
| 契约测试 | 1项通过 |
| 全量测试 | 44项通过 |
| Ruff格式与规则 | 通过 |
| mypy strict | 37个源码文件，0问题 |
| Bandit | 通过 |
| pip-audit | 无已知漏洞 |

## 运行时验收

使用验证容器中的真实Uvicorn进程、Git忽略的
`.local/phase06-acceptance.sqlite3`和合成消息执行：

| 检查 | 结果 |
|---|---|
| 健康检查 | PASS |
| 相同POST次数 | 10 |
| 首次处理 | 1，`duplicate=false` |
| 持久重复短路 | 9，均`duplicate=true` |
| 处理状态 | `sent` |
| 重启前会话 | 2条，`buyer,service` |
| 使用同一SQLite重启 | PASS |
| 重启后会话 | 与重启前完全一致 |
| 扩展监听端口 | 验收后关闭 |

第一次HTTP循环命令因Windows到容器shell的多层引号截断，没有触达业务；第二轮
改用内存Base64传递相同脚本后通过。两个Uvicorn均收到`TERM`且端口关闭；验证
容器PID 1没有回收已退出子进程，保留两个`defunct`条目，但不存在运行中的扩展
服务，也没有删除失败现场或数据库。

## 数据库与迁移

- 新增扩展内schema：
  `extensions/pdd-customer-service/app/repositories/sql/001_reliability.sql`
- `PRAGMA user_version=1`
- 表：`inbox_messages`、`outbox_messages`、`reply_leases`、
  `audit_events`
- 默认路径：`.local/pdd-reliability.sqlite3`
- 新增TGO Alembic迁移：0
- 修改TGO数据库：0

## 安全与边界

- `.env`和`*.sqlite3`继续被Git忽略；
- `.env.example`只有空的本地路径变量和安全说明；
- 新增依赖：0；
- 依赖锁文件变化：0；
- TGO核心`repos/*`修改：0；
- 真实密钥、真实买家数据和真实业务载荷：0；
- 审计表和fallback日志不保存正文；
- 15个TGO核心容器在实施期间保持`healthy`。

Gitleaks门禁：

- 完整受控源码2003个文件，22项既有基线；
- 阶段6差异28个文件；
- 整文件差异快照报告1项既有`.env.example`空模板误报，和阶段5基线的变量名、
  空值长度及上下文一致，仅行号因新增两行说明而移动；
- 阶段6新增候选0；
- 候选值未输出。

## 文件摘要

新增：

- 可靠性领域模型、SQLite仓库、schema和可靠编排服务；
- 可靠性单元/集成测试和可控合成fixture；
- 消息可靠性运行手册、设计、计划、验证日志和本报告。

修改：

- Mock Adapter失败注入与双向幂等；
- FastAPI应用工厂、lifespan、路由错误映射和依赖注入；
- 模型、仓库和服务导出；
- `.env.example`与扩展开发手册。

根Compose、根Makefile、依赖锁文件和`repos/*`均未修改。

## 回滚

不修改当前阶段分支，创建指向阶段5安全状态的新分支：

```bash
git switch -c rollback/phase-06 phase-05-complete
```

检查阶段6安全标签：

```bash
git show --stat phase-06-complete
git diff phase-05-complete..phase-06-complete
```

只停止本地扩展时使用前台`Ctrl+C`或向已确认的扩展PID发送`TERM`。回滚命令不
删除SQLite、Docker卷、数据库、分支或标签。

## 下一阶段门禁

只有以下条件全部满足后才能创建`phase/07-knowledge-framework`：

1. 全部格式、Ruff、mypy、测试、安全与Gitleaks门禁为PASS；
2. `repos/*`变化为0；
3. 工作区已提交且干净；
4. 本地标签、远程分支、远程标签均指向同一阶段6提交。
