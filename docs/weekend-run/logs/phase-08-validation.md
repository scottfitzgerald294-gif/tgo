# 阶段8验证日志

## 执行环境

- 分支：`phase/08-human-handoff-rules`
- 阶段起点：`phase-07-complete`（`9b7f615`）
- 设计提交：`110d9eb`
- 计划提交：`cd1df66`
- 风险类型隔离提交：`b6c8a9b`
- 验证容器：`pdd-weekend-verifier`
- Python：3.11.15
- Poetry：2.4.1
- 真实公司资料、真实PDD、真实模型、TGO业务API和外部付费调用：0

## RED/GREEN证据

| 编号 | 行为 | 状态 | 命令与证据 |
|---|---|---|---|
| CFG01-RED | 严格JSON兼容YAML配置合同 | RED（预期） | 风险模型、配置类型和加载器尚不存在 |
| CFG01-GREEN | 严格JSON兼容YAML配置合同 | GREEN | 正常加载、缺文件、未知字段、重复优先级、非法原因码、空关键词和重复claim id合同通过；异常不含绝对路径或正文 |
| RULE01-RED | 用户规则优先级、知识/故障规则和禁止承诺 | RED（预期） | `RiskRuleEngine`尚不存在，73项参数化行为不能收集或执行 |
| RULE01-GREEN | 用户规则优先级、知识/故障规则和禁止承诺 | GREEN | 73项通过；含四个验收短语、68个独立规则场景、四模式保持和组合优先级 |
| DB01-RED | schema v1到v2无损迁移 | RED（预期） | `002_handoff.sql`和人工转接仓库尚不存在 |
| DB01-GREEN | schema v1到v2无损迁移 | GREEN | v1数据保留，`user_version=2`，新表和索引存在；未知schema保留现场并脱敏失败 |
| DB02-RED | 状态机、队列、审计与事务原子性 | RED（预期） | 状态转换、开放队列唯一和无正文审计尚不存在 |
| DB02-GREEN | 状态机、队列、审计与事务原子性 | GREEN | 仓库5项及阶段6存储3项通过；非法转换前后状态、lease、队列和审计不变 |
| SVC01-RED | 风险决策持久化、人工保持和显式恢复 | RED（预期） | `HandoffService`尚不存在 |
| SVC01-GREEN | 风险决策持久化、人工保持和显式恢复 | GREEN | 安全问题保持AI；风险问题进入WAITING；高风险无确认拒绝，确认后恢复 |
| RACE01-RED | AI已取得旧epoch后人工接管 | RED（预期） | 发送前尚未用会话模式再次验证reply lease |
| RACE01-GREEN | AI已取得旧epoch后人工接管 | GREEN | 人工事务递增epoch并切换owner；旧AI任务发送0、任务failed并记录`ai_reply_blocked` |
| API01-RED | evaluate、queue与WAITING阻断 | RED（预期） | 人工转接路由和应用注入链尚未接入 |
| API01-GREEN | evaluate、queue与WAITING阻断 | GREEN | 退款进入WAITING，队列不含正文，后续模拟消息failed且Adapter发送0 |
| API02-RED | claim、resume、close与安全错误映射 | RED（预期） | 新增测试稳定复现未知会话claim返回409而不是404 |
| API02-GREEN | claim、resume、close与安全错误映射 | GREEN | 根因是`_required_state()`误抛转换异常；改为既有`HandoffNotFoundError`后7项API测试通过 |

所有生产行为均先有对应失败测试，再写最小实现。没有删除测试、跳过测试、降低
断言、关闭安全检查、忽略异常或用空实现冒充完成。

## 定向与回归测试

| 检查 | 结果 |
|---|---|
| 阶段8规则、仓库、服务、可靠性和API定向套件 | PASS；103项 |
| 阶段5—7集成、契约、知识服务和可靠服务回归 | PASS；55项 |
| API聚焦套件 | PASS；7项 |
| 单元测试 | PASS；163项 |
| 集成测试 | PASS；19项 |
| 全量测试 | PASS；183项，含1项Real PDD禁用契约 |

阶段7全量为95项；阶段8新增81项单元和7项集成，共新增88项，契约测试保持1项。

## 调试记录

1. API剩余行为首次运行稳定复现“未知会话领取返回409”。异常从
   `SQLiteHandoffRepository._required_state()`流向API；仓库已经定义
   `HandoffNotFoundError`且API已映射404，但该方法误抛
   `HandoffTransitionError`。第一轮只改变异常类型，API 7项转绿。
2. 首轮lint在格式门禁发现7个新文件未格式化；运行项目`make format`后格式门禁
   通过。随后Ruff发现2个导入块顺序错误，由Ruff机械整理。
3. mypy随后报告两处可空状态直接访问和一个测试故障仓库缺少签名。只增加非空
   断言及与Protocol一致的类型标注，重新运行lint后58个源码文件0问题。
4. 首次实际进程验收的Windows/容器多层here-doc引号在进入业务前截断，没有
   发出请求或修改数据库。改用标准输入后进入业务，但PowerShell管道改写了内联
   脚本的非ASCII字符，表现为退款关键词未命中且中文固定回复比较同时失败。使用
   ASCII Unicode转义后完整链通过；应用代码未为验收工具问题做任何修改。
5. 首次SQLite元数据统计误把`status`列放在`inbox_messages`。对照
   `001_reliability.sql`确认状态属于`outbox_messages`，改用主键关联后schema、
   状态、队列、审计和消息状态计数全部通过。
6. 第一次停止进程的轮询只使用`kill -0`，把已经完成shutdown的zombie PID误判
   为运行中。`ps`、端口和日志共同证明端口已关闭且Uvicorn完成正常shutdown，
   因此没有强杀或清理现场。

每个错误均在两轮根因分析限制内解决。失败SQLite、Uvicorn日志、Gitleaks报告和
受控源码快照均保存在Git忽略目录，没有删除或覆盖。

## 真实Uvicorn本地进程验收

验收使用：

```text
.local/phase08-acceptance-20260718-205825.sqlite3
.local/phase08-uvicorn-20260718-205825.log
127.0.0.1:18091
```

文件均被`.local/`忽略，只包含合成标识和本地验收状态。验收完成后Uvicorn正常
停止，SQLite和日志保留。

| 检查 | 结果 |
|---|---|
| 健康检查 | PASS |
| “我要退款”确定性路由 | PASS；`refund_compensation_price` |
| 转人工后模式和队列 | PASS；`WAITING_HUMAN`、1个waiting项 |
| 队列正文泄露 | PASS；消息正文和`message_text`字段均不存在 |
| WAITING下新消息 | PASS；`failed` |
| 显式领取 | PASS；`HUMAN` |
| high风险无确认恢复 | PASS；409 |
| high风险显式确认恢复 | PASS；`AI` |
| 恢复后固定测试回复 | PASS；`sent`且内容为阶段5固定回复 |
| 显式关闭 | PASS；`CLOSED` |
| CLOSED下新消息及恢复 | PASS；消息`failed`、恢复409 |
| schema | PASS；`user_version=2` |
| 关闭后的消息状态 | PASS；2条failed、1条sent |
| 转接审计 | PASS；5条，审计表正文列0 |
| 同一SQLite重启 | PASS；CLOSED、closed队列历史和5条审计保持 |
| 重启后新消息 | PASS；`failed` |

## 最终质量与安全门禁

| 命令或检查 | 结果 |
|---|---|
| `make format` | PASS；58个Python源码无需变化 |
| `make lint` | PASS；Ruff通过，mypy检查58个源码文件、0问题 |
| `make test-unit` | PASS；163项 |
| `make test-integration` | PASS；19项 |
| `make test` | PASS；183项 |
| `make security-check` | PASS；Bandit、pip-audit和`.env`忽略检查通过 |
| `git diff --check` | PASS |
| `repos/*`工作区和阶段差异 | PASS；0 |
| 依赖及锁文件变化 | PASS；0 |
| `.env`、验收SQLite和日志忽略 | PASS |
| TGO核心容器 | PASS；15个运行且15个`healthy` |
| 阶段8本地Uvicorn | PASS；验收后正常停止，运行中进程0 |

## Gitleaks门禁

- 阶段8最终受控源码：2039个文件；
- 当前完整候选：22；
- 阶段7完整基线：22；
- 规则分布均为`curl-auth-header=2`、`generic-api-key=17`、
  `stripe-access-token=3`；
- 按规则ID、相对文件路径和同路径数量归一化比较：新增0、移除0；
- 候选值输出：0；
- 最终扫描报告：
  `data/weekend-run/phase-08/final-gitleaks-full.json`；
- 受控源码和报告位于Git忽略目录，失败和基线现场未删除。
