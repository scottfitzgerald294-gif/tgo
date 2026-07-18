# 阶段6设计：消息可靠性账本、重试与回复所有权

## 批准依据

用户在无人值守执行附件中明确授权自动执行到阶段8，并为阶段6指定唯一键、
Webhook去重、幂等、重放窗口、五种发送状态、指数退避、死信、会话级并发、
AI/人工互斥、重启恢复、超时、数据库不可用和失败审计等完整验收项。

本设计只选择这些已批准要求的本地实现方式，不接入真实PDD、真实TGO业务API、
真实模型、生产数据库或付费服务。用户要求无人值守连续执行，因此附件中的明确
范围和验收标准作为本阶段设计预批准依据。

## 目标

把阶段5的单次进程内模拟链路升级为可持久恢复、可去重、可审计的本地可靠消息
处理器，同时保持：

- 所有代码位于`extensions/pdd-customer-service/`；
- 不修改TGO核心`repos/*`；
- 只使用`FAKE/TEST`数据；
- Real PDD Adapter继续显式禁用；
- 不实现阶段7知识框架或阶段8风险规则。

可靠性不变量：

1. 同一`shop_id + message_id`最多进行一次业务接收。
2. 同一`reply_id`在Mock外部平台视图最多出现一次。
3. 同一完整会话键串行，不同会话可以并行。
4. 人工所有权优先于自动回复，旧AI epoch不能发送。
5. 任何可重试或最终失败都有不含正文的追加审计。
6. 没有持久账本时不进行无账本的外部发送。

## 方案比较

### 方案A：扩展自有SQLite Inbox/Outbox/Audit账本

使用Python 3.11标准库`sqlite3`和版本化SQL初始化脚本。每次操作使用短事务，
数据库唯一约束负责原子去重；异步服务通过`asyncio.to_thread`执行阻塞数据库
调用。优点是零新增依赖、重启后可恢复、可测试数据库不可用和事务边界，不耦合
TGO核心。限制是第一版仅支持单Connector进程；多副本分布式锁和生产数据库属于
阶段9以后准备项。

### 方案B：复用TGO PostgreSQL

可以直接获得生产级并发和现有容器，但会让Connector直接访问TGO数据库，违反
阶段2集成边界和“服务间只走API”的规则，也会引入TGO核心schema迁移，因此拒绝。

### 方案C：内存状态加JSON追加日志

实现较少，但无法可靠提供唯一约束、原子状态迁移、并发去重或崩溃恢复；日志截断
和部分写入也难以验证，因此不能满足阶段6验收。

选择方案A。

## 文件和组件边界

### 1. 可靠性领域模型

`app/models/reliability.py`定义：

- `MessageKey`：`shop_id + message_id`；
- `MessageStatus`：`pending / sent / failed / retrying / dead_letter`；
- `ReplyOwner`：`ai / human`；
- `RetryPolicy`：最大尝试次数、基础退避、最大退避、发送超时、重放窗口和未来
  时钟容差；
- `ReliabilityRecord`：持久消息和固定reply的完整恢复信息；
- `AuditRecord`：不含正文的状态、事件、尝试和原因码；
- `RecoverySummary`：恢复扫描和结果计数。

阶段5的`SimulationResult`增加向后兼容的`processing_status`、`duplicate`和
`attempts`字段；旧调用默认仍表示一次成功发送。

### 2. SQLite可靠性仓库

`app/repositories/sql/001_reliability.sql`创建：

```text
inbox_messages
outbox_messages
reply_leases
audit_events
```

关键约束：

- `inbox_messages`主键为`(shop_id, message_id)`；
- 每条Inbox只有一个Outbox；
- `outbox_messages.reply_id`全局唯一；
- Outbox保存`retryable`、`last_reason`和`next_attempt_at`，永久阻止与瞬时失败可
  明确区分；
- `reply_leases`主键为完整
  `(shop_id, buyer_id, conversation_id)`；
- `audit_events`只追加，不更新和删除。

数据库保存合成消息正文以支持本地恢复和会话查询，但普通日志和审计表不保存
正文。默认文件为扩展内`.local/pdd-reliability.sqlite3`，现有`*.sqlite3`及
sidecar忽略规则覆盖它。`.env.example`只增加空的本地路径变量和安全说明。

仓库构造函数只保存路径，不打开文件；`initialize()`在FastAPI lifespan或测试
显式调用时创建目录、应用schema并设置`PRAGMA user_version=1`。导入应用仍无
数据库、网络或模型副作用。

所有`sqlite3.OperationalError`转换为
`PersistenceUnavailableError`。新消息无法原子写入账本时，处理器停止且不调用
Adapter，并记录固定的脱敏fallback日志。

### 3. 原子Claim和去重

入站流程先验证时间，再在单一事务中尝试插入Inbox和预生成Outbox：

1. 生成稳定`MessageKey`、`trace_id`和`reply_id`；
2. `INSERT ... ON CONFLICT DO NOTHING`；
3. 新插入返回`is_new=True`；
4. 冲突读取既有记录并追加`duplicate_detected`审计；
5. 重复请求直接返回既有结果，不再次调用Adapter、会话仓库或发送。

阶段6只使用模拟字段中的`shop_id + message_id`，不把它声称为真实PDD幂等规则。
真实dedupe key仍必须由未来官方合同确定。

### 4. 重放窗口

处理器使用可注入UTC时钟：

- 消息时间早于当前时间300秒：拒绝；
- 消息时间晚于当前时间60秒：拒绝；
- 边界值允许；
- 被拒绝消息不进入Inbox、不调用Adapter；
- 普通日志只记录固定事件、trace和原因码。

这只是本地模拟防重放，不猜测真实PDD签名、nonce或官方时效规则。

### 5. 状态机、重试和死信

```text
pending
  ├─ send success → sent
  ├─ transient failure → failed → retrying → send
  ├─ timeout → failed → retrying → send
  ├─ human owner → failed
  └─ max attempts reached → dead_letter
```

规则：

- 默认最多3次发送尝试；
- 退避为`base_delay * 2^(attempt-1)`，并受`max_delay`限制；
- 每次发送使用同一`reply_id`；
- `asyncio.wait_for`强制发送超时；
- Mock Adapter可配置前N次发送失败，并按`reply_id`幂等记录成功送达；
- 每次失败、重试、成功和死信都在同一状态更新事务中追加审计；
- 不吞掉`CancelledError`，服务中断时保留`retrying`供恢复。

测试时使用可注入时钟/休眠器，不等待真实指数退避时间。

### 6. 会话顺序与并行

`ConversationLockRegistry`为每个完整
`shop_id + buyer_id + conversation_id`维护独立`asyncio.Lock`。

- 同一会话按照公平锁的获取顺序串行处理；
- 不同会话使用不同锁，可并行进入Adapter；
- 锁只保护单进程编排，不冒充分布式锁；
- Inbox唯一约束仍负责并发重复消息的最终原子裁决。

测试使用可控阻塞Adapter证明同会话不会重叠、不同会话确实同时进入发送阶段，
并检查内容不串线。

### 7. AI/人工回复所有权

阶段6只实现最小回复租约，不实现阶段8完整会话状态机：

```text
reply_lease
  owner: ai | human
  epoch: 单调递增整数
```

- 自动处理开始时仅在当前owner不是`human`时取得AI epoch；
- 每次Adapter发送前再次核对owner和epoch；
- 人工接管原子设置`owner=human`并递增epoch；
- 人工owner存在时自动回复标记`failed`，审计原因
  `human_owner_blocks_ai`，同时设置`retryable=false`，Adapter发送次数为0；
- 恢复AI必须调用显式本地服务操作并产生新epoch；
- 阶段6不提供正式人工队列或外部管理API，阶段8再实现完整状态转换。

### 8. 重启恢复

FastAPI lifespan执行：

1. `store.initialize()`；
2. 扫描`pending`以及`retryable=true`的`failed / retrying`记录；
3. 对到期记录按会话锁恢复；
4. 使用已持久化的原消息、trace、reply_id和尝试次数继续；
5. 已`sent`、`dead_letter`或`retryable=false`的人工阻止记录不重复发送。

恢复测试在第一次失败进入`retrying`休眠时取消旧处理任务，再用相同SQLite文件和
代表外部平台的同一个Mock Adapter创建新服务，证明任务恢复且买家只看到一次
回复。Mock Adapter的入站键和reply_id也保持幂等。

### 9. 会话查询

可靠服务从SQLite账本生成会话快照：

- 买家消息按Inbox接收序号出现一次；
- 只有`sent`的Outbox显示为客服消息；
- 重试失败和死信不伪造已送达回复；
- 进程重启后GET仍能读取已持久的合成会话。

阶段5内存Adapter查询仍保留用于其单元测试，默认应用改用可靠服务查询。

### 10. API错误

- 数据库不可用：HTTP 503，不调用Adapter；
- 时间超出重放窗口：HTTP 409，不进入账本；
- 正常首次处理或重复已处理消息：保持阶段5响应结构并增加可靠性字段；
- 达到死信：返回结果中`processing_status=dead_letter`，不伪造发送成功；
- 未知会话：404。

所有异常响应不包含数据库路径、SQL、正文或内部堆栈。

数据库自身不可用时无法向同一数据库追加审计，因此该唯一场景写固定事件
`reliability_database_unavailable`到脱敏结构化fallback日志；数据库恢复后的
下一次Claim再写持久审计。报告必须把持久审计和fallback审计分开计数，不能把
不可持久化的故障伪装为数据库审计成功。

## 测试设计

严格逐项RED、GREEN：

1. 状态、重试策略和重放窗口模型测试；
2. SQLite schema、原子Claim、审计追加和重新打开测试；
3. 同一消息顺序提交10次，只接收和成功发送一次；
4. 前两次发送失败、第三次成功，attempt为3且买家只看到一条回复；
5. 两个买家并行且内容不串线；
6. 同一会话两条消息顺序处理且发送区间不重叠；
7. 人工owner阻止自动发送并产生审计；
8. 处理中断后新服务从同一SQLite文件恢复；
9. 最大次数后进入`dead_letter`；
10. 真实`asyncio.wait_for`超时进入重试审计；
11. 数据库首次不可用时Adapter调用为0，恢复后可重新提交；
12. API重复、503、409和持久会话集成测试；
13. 阶段5全部20项测试继续通过。

## 安全和范围

- 不新增Python依赖、Docker服务或外部端口；
- 不访问真实PDD、TGO业务API、模型、生产数据库或付费服务；
- 不记录正文、SQL参数、数据库绝对路径、凭据或完整外部负载；
- 不删除数据库或Docker卷；
- 不实现真实Webhook验证或真实PDD应答；
- 不实现阶段7知识结构；
- 不实现阶段8风险规则、人工队列或完整会话状态机；
- `repos/*`修改必须保持0；
- Gitleaks受控源码基线不得超过22，阶段6差异必须为0。

## 验收

- 同一消息提交10次，只处理一次；
- 失败两次后第三次成功，买家只看到一次；
- 不同买家并行且不串线；
- 同一会话严格串行；
- 人工模式下自动回复无法发送；
- 重启后未完成任务恢复；
- 最大尝试次数后进入`dead_letter`；
- 发送超时和数据库不可用均有脱敏审计；
- 全部失败可按trace、状态、尝试和原因码追踪；
- 阶段5API兼容、健康检查和测试保持通过；
- 无真实凭据、无新依赖、无TGO核心修改。
