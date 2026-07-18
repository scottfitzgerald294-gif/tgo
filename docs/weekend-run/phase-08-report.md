# 阶段8报告：确定性风险路由与人工转接

## 结论

阶段8自动验收为`PASS`。本阶段只实现扩展自有、确定性、本地SQLite的风险路由、
人工转接状态机和合成客服队列；没有调用真实拼多多、真实模型、TGO业务API、
真实客服账号、订单/退款/地址接口、真实公司资料、生产环境或付费服务。

- 分支：`phase/08-human-handoff-rules`
- 阶段起点：`phase-07-complete`（`9b7f615`）
- 设计提交：`110d9eb`
- 计划提交：`cd1df66`
- 类型隔离提交：`b6c8a9b`
- 阶段最终提交：由`phase-08-complete^{commit}`唯一解析
- 阶段标签：`phase-08-complete`
- 主分支合并、Pull Request和强制推送：0

## 已实现范围

```text
合成消息/有类型事实
→ 严格JSON兼容YAML配置
→ 确定性规则优先级
→ continue_ai / handoff / blocked
→ SQLite schema v2原子状态、队列、审计和reply lease
→ 固定转人工提示或阶段5固定测试回复
```

实现内容：

- 独立`HandoffRiskLevel`，不放宽阶段7知识`RiskLevel`；
- 14个稳定原因码、四种会话模式和三种路由动作；
- 买家人工请求、投诉/法律、退款/赔偿/改价、订单修改、安全伤害、严重质量、
  知识缺失/冲突/过期、服务故障、连续未解决和禁止承诺规则；
- NFKC、控制字符移除、空白压缩和casefold文本规范化；
- schema v1到v2无损迁移；
- `AI / WAITING_HUMAN / HUMAN / CLOSED`状态转换约束；
- 转接时同事务切换模式、队列、无正文审计和reply lease epoch；
- AI取得lease和发送前两次模式/epoch校验；
- 固定转人工提示、开放客服队列和显式领取/恢复/关闭API；
- high/critical恢复必须显式风险确认；
- 未知会话404、非法转换409、非FAKE/TEST标识422、持久化故障脱敏503；
- 规则、迁移、状态机、竞态、API、重启和回归测试；
- 人工转接运行手册、开发手册入口和本地SQLite安全说明。

## 安全不变量

- `WAITING_HUMAN/HUMAN/CLOSED`不能取得或继续使用AI reply lease；
- 人工转接与lease epoch变更在同一SQLite事务内完成；
- AI不能自行从人工模式恢复；
- 高风险恢复必须由FAKE/TEST操作者显式确认；
- `CLOSED`是终态；
- 知识无效、服务故障或不能证明安全时默认转人工；
- 配置或持久化不可用时AI不发送；
- 队列和转接审计不保存消息正文、候选回复、密钥或真实资料；
- 所有本地接口只接受FAKE/TEST会话标识和操作者。

## TDD与故障证据

完整逐项RED/GREEN和调试记录见
[`logs/phase-08-validation.md`](logs/phase-08-validation.md)。

关键证据：

- 配置、模型、规则、仓库、状态机、服务和API均先观察缺失行为RED；
- 73项规则测试覆盖68个独立场景、模式保持和优先级；
- v1到v2迁移保留阶段6数据，未知schema不覆盖；
- 人工在AI发送前接管会使旧epoch失效且Adapter发送0；
- 未知会话claim首次返回409，定位错误异常类型后最小修复为404；
- 所有工具链错误均在两轮根因分析限制内解决并保留现场。

最终自动化结果：

| 检查 | 结果 |
|---|---|
| 单元测试 | 163项通过 |
| 集成测试 | 19项通过 |
| 契约测试 | 1项通过 |
| 全量测试 | 183项通过 |
| Ruff格式与规则 | 通过 |
| mypy | 58个源码文件，0问题 |
| Bandit | 通过 |
| pip-audit | 无已知漏洞 |

## 实际进程验收

使用真实Uvicorn、Git忽略的新SQLite和FAKE/TEST标识完成：

1. 健康检查；
2. “我要退款”进入WAITING和单一开放队列；
3. WAITING下新消息AI不发送；
4. 显式领取进入HUMAN；
5. high风险无确认恢复返回409；
6. 显式确认后恢复AI并发送阶段5固定测试回复；
7. 关闭后新消息和恢复均被阻止；
8. 重启后schema v2、CLOSED模式、closed队列历史和5条无正文审计保持。

验收完成后进程正常shutdown，SQLite和日志保存在`.local/`且未删除。

## 持久化、依赖与迁移

- 扩展SQLite schema：`1 → 2`；
- 新增表：`conversation_handoff_states`、`handoff_queue`、
  `handoff_audit_events`；
- 新增索引：开放队列唯一索引及队列/审计读取索引；
- 阶段6 Inbox、Outbox、lease、会话和审计表保留；
- 新增TGO Alembic迁移：0；
- 修改TGO数据库：0；
- 新增依赖：0；
- 依赖锁文件变化：0；
- 新增Docker服务：0。

## 安全与边界

- `.env`、`.local/`、SQLite、日志和扫描现场继续被Git忽略；
- `.env.example`只增加共享本地SQLite的空值安全说明；
- TGO核心`repos/*`修改：0；
- 根Compose和根Makefile修改：0；
- 真实密钥、真实公司资料、真实买家数据和真实业务载荷：0；
- Gitleaks完整候选22，等于阶段7基线22，归一化新增0；
- 候选值未输出；
- 15个TGO核心容器均为`healthy`，阶段8本地Uvicorn验收后已正常停止。

## 文件摘要

新增：

- 两个严格风险规则配置；
- 人工转接领域模型、规则引擎、SQLite v2迁移和仓库；
- 人工转接服务与本地API；
- 规则、迁移、状态机、服务、竞态和API测试；
- 合成测试fixture、人工转接手册、验证日志和本报告。

修改：

- 应用工厂增加共享SQLite的转接仓库、规则引擎和路由；
- 阶段6可靠存储增加模式感知的AI lease门禁及schema v2兼容；
- 模型、仓库和服务导出；
- `.env.example`和扩展开发手册。

`repos/*`、根Compose、根Makefile、依赖清单和锁文件均未修改。

## 明确未实现

- 真实拼多多API、Webhook签名、店铺授权或自动回复；
- 真实模型、Embedding、RAG、重排或自动风险学习；
- TGO Waiting Queue、真实Visitor `ai_disabled`或浏览器客服工作台；
- 真实客服账号、SLA、排班、通知或分配算法；
- 订单、退款、赔偿、改价、地址、物流或售后操作；
- 真实商品、政策、公司文档或买家数据；
- 云部署、域名、生产权限或阶段9业务功能。

## 回滚

不修改当前阶段分支，创建指向阶段7安全状态的新分支：

```bash
git switch -c rollback/phase-08 phase-07-complete
```

检查阶段8安全标签：

```bash
git show --stat phase-08-complete
git diff phase-07-complete..phase-08-complete
```

该回滚不删除SQLite、JSON、日志、Docker卷、数据库、分支或标签。需要查看阶段8
持久状态时先按运行手册使用SQLite在线备份API创建新副本，不覆盖原文件。

## 阶段9停止门禁

阶段8完成后禁止继续实现真实RAG、模型、拼多多接口、店铺授权、自动回复、生产
部署或真实业务数据导入。后续本次执行只允许创建阶段9—18材料准备清单、最终报告
和状态文件，且`safe_to_start_phase_09`保持`false`。
