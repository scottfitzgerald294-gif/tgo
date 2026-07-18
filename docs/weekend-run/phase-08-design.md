# 阶段8设计：确定性风险路由与人工转接

## 批准依据

用户在无人值守执行附件中明确授权自动执行到阶段8，并为本阶段指定了规则优先级、
配置文件、风险等级、原因码、四种会话模式、状态转换、AI/人工互斥、固定转接
提示、审计、客服队列、至少50条规则测试和验收短语。

本设计只把这些已批准要求固化为可测试的本地实现。附件要求项目所有者离开期间
连续执行，因此其明确规则、验收和“禁止真实模型/PDD”边界作为设计批准；不新增
需要真实业务选择的功能。

## 目标与安全不变量

目标是让阶段5—7的本地模拟链在确定性规则下决定“继续AI测试流程、转人工或
禁止处理”，并把人工转接持久化为可审计状态。

安全不变量：

1. 人工优先于AI；`WAITING_HUMAN/HUMAN/CLOSED`不能取得有效AI租约。
2. 人工转接事务同时改变会话模式、客服队列和回复租约epoch。
3. AI不能自行从`HUMAN`或`WAITING_HUMAN`恢复；恢复必须有显式合成操作者。
4. 高风险会话恢复AI还必须显式确认风险已由人工复核。
5. `CLOSED`是终态，不允许恢复或产生新回复。
6. 无有效知识、知识冲突/过期、服务故障和连续两次未解决默认转人工。
7. 规则、状态、队列或审计持久化故障时不发送AI回复。
8. 配置、日志和审计不保存真实资料、消息正文、候选回复或密钥。

## 方案比较

### 方案A：同一SQLite、独立人工转接仓库

在现有扩展SQLite schema上增加v2迁移；新
`SQLiteHandoffRepository`负责会话状态、队列和转接审计，并在同一个
`BEGIN IMMEDIATE`事务中更新现有`reply_leases`。现有可靠服务在取得AI租约和
发送前同时检查会话模式。

优点：

- 会话模式、队列和回复所有权原子一致；
- 复用阶段6持久化和epoch互斥，不建立第二套回复真相；
- 重启后状态与队列仍在；
- 新代码集中在扩展，不修改TGO核心。

代价是增加一个扩展内schema迁移，并让可靠仓库读取新的会话模式表。

### 方案B：独立人工转接数据库

实现边界更独立，但模式和阶段6租约分属两个事务。任何一个数据库写失败都会产生
“状态已转人工但租约仍为AI”或相反的恢复问题，需要额外补偿状态，不适合本阶段
的竞态验收，因此不选。

### 方案C：进程内状态机和队列

代码最少，但进程重启丢失人工接管状态，旧Outbox可能恢复发送，违反持久阻断与
安全默认，因此不选。

选择方案A。

## 文件与边界

阶段8代码只位于：

```text
extensions/pdd-customer-service/
  app/models/handoff.py
  app/repositories/handoff.py
  app/repositories/sql/002_handoff.sql
  app/services/risk_routing.py
  app/services/handoff.py
  app/api/handoff.py
```

配置位于阶段3预留的根目录：

```text
config/pdd/transfer_rules.yml
config/pdd/forbidden_claims.yml
```

配置使用JSON兼容的YAML 1.2写法，由Python标准库`json`严格解析。JSON是YAML
1.2的合法子集；这样无需增加PyYAML依赖，也不存在不安全对象构造。扩展启动时
校验完整类型、重复优先级、空关键词、未知字段和规则版本，失败则应用启动失败，
不降级为空规则。

本阶段不修改`repos/*`，不调用TGO API、RAG、模型或PDD，不创建真实人工账号。

## 领域模型

### 风险等级

```text
low
medium
high
critical
```

`high/critical`会把会话标记为高风险；显式恢复AI还必须
`risk_acknowledged=true`。

### 会话模式

```text
AI
WAITING_HUMAN
HUMAN
CLOSED
```

### 路由动作

```text
continue_ai
handoff
blocked
```

`continue_ai`只表示可继续阶段5固定测试回复或后续受控流程，不调用真实模型。
`handoff`返回固定文本：

```text
您的问题需要人工客服进一步处理，已为您转接，请稍候。
```

`blocked`只用于`CLOSED`终态，不产生回复或新队列项。

### 原因码

按用户优先级固定：

```text
human_already_active
human_requested
complaint_legal_regulatory
refund_compensation_price
order_change
product_safety_injury
severe_quality
no_valid_knowledge
knowledge_conflict
knowledge_expired
service_failure
repeated_unresolved
```

附加输出安全原因：

```text
forbidden_claim
conversation_closed
```

附加原因不改变用户给出的入站规则1—12顺序；`forbidden_claim`只校验候选回复，
`conversation_closed`是状态机终态保护。

## 确定性规则

`RoutingContext`只接收：

```text
conversation_key
message_text
knowledge_status = valid | missing | conflict | expired
service_available
unresolved_count
candidate_reply（可空，仅本地合成文本）
```

执行顺序严格为：

1. `CLOSED`：`blocked`；
2. 当前`WAITING_HUMAN/HUMAN`：保持人工模式；
3. 买家明确要求人工；
4. 投诉、举报、法律、监管；
5. 退款、赔偿、改价；
6. 修改地址、取消订单、修改订单；
7. 产品安全、伤害；
8. 严重质量问题；
9. 无有效知识；
10. 知识冲突；
11. 知识过期；
12. 服务故障；
13. `unresolved_count >= 2`；
14. 候选回复命中禁止承诺；
15. 其余且知识有效：`continue_ai`。

这里的第2项对应用户规则“人工已经接管”，后续用户规则依次保持相同相对顺序。
未知商品参数由调用方明确传入`knowledge_status=missing`，模型/接口故障由
`service_available=false`表达，不使用模型推测。

文本只做Unicode NFKC、大小写折叠、空白压缩和控制字符移除，再执行配置关键词
子串匹配。第一版不使用正则、机器学习、分词或模糊匹配，避免不可解释命中。

## 配置合同

`transfer_rules.yml`包含：

```text
schema_version
handoff_message
text_rules[]
  priority
  reason_code
  risk_level
  keywords[]
```

只配置用户规则2—7的文本类别；状态、知识、服务和次数规则由有类型字段触发。
优先级必须唯一且严格递增，原因码必须属于固定枚举，关键词去重后非空。

`forbidden_claims.yml`包含：

```text
schema_version
claims[]
  claim_id
  risk_level
  phrases[]
```

命中任何禁止承诺时只返回原因码和风险等级，不在日志或审计中保存候选回复。

## SQLite schema v2

保留阶段6全部表和数据，新增：

```text
conversation_handoff_states
  shop_id
  buyer_id
  conversation_id
  mode
  risk_level
  reason_code
  updated_at

handoff_queue
  queue_id
  shop_id
  buyer_id
  conversation_id
  status = waiting | claimed | closed
  reason_code
  risk_level
  created_at
  claimed_by
  claimed_at
  closed_at

handoff_audit_events
  audit_id
  shop_id
  buyer_id
  conversation_id
  event
  from_mode
  to_mode
  reason_code
  risk_level
  operator
  created_at
```

开放队列对完整会话键使用部分唯一索引，确保最多一个`waiting/claimed`条目。
审计不保存买家文本、候选回复或知识正文。

初始化规则：

- 新数据库：顺序执行`001_reliability.sql`和`002_handoff.sql`；
- schema v1：只执行v2迁移，保留Inbox、Outbox、会话和审计；
- schema v2：只验证；
- 其他版本：脱敏失败，不自动重建或删除。

## 状态转换

```text
无记录 ≡ AI

AI → WAITING_HUMAN       确定性规则要求转接
WAITING_HUMAN → HUMAN    客服显式领取
WAITING_HUMAN → AI       显式恢复
HUMAN → AI               显式恢复
AI → CLOSED              显式关闭
WAITING_HUMAN → CLOSED   显式关闭
HUMAN → CLOSED           显式关闭
CLOSED → CLOSED          幂等读取，不追加重复事件
```

禁止：

- `AI → HUMAN`绕过队列领取；
- `HUMAN/WAITING_HUMAN → AI`无操作者；
- 高风险恢复但未确认风险；
- `CLOSED`恢复或重新转接。

转人工事务：

1. `BEGIN IMMEDIATE`；
2. 读取当前模式和reply lease；
3. 将lease owner设为`human`并递增epoch；
4. 将模式设为`WAITING_HUMAN`；
5. 插入唯一waiting队列项；
6. 追加无正文审计；
7. 提交。

人工已经领取时再次命中规则保持`HUMAN`、不重复排队；旧AI epoch仍失效。

## AI与人工竞态

阶段6可靠服务增加两道模式检查：

1. `acquire_ai_lease`：模式缺失或`AI`才可返回AI epoch；
2. `lease_is_current`：发送前要求模式仍为`AI`且owner/epoch一致。

人工转接在同一数据库事务内切换模式并递增epoch。无论AI处于Claim、Adapter接收、
退避、恢复还是发送前，下一次租约检查都会失败并记录`ai_reply_blocked`，不会
调用Mock发送接口。

## 客服队列接口

本地FastAPI增加：

```text
POST /handoff/evaluate
GET  /handoff/queue
POST /handoff/conversations/{shop}/{buyer}/{conversation}/claim
POST /handoff/conversations/{shop}/{buyer}/{conversation}/resume
POST /handoff/conversations/{shop}/{buyer}/{conversation}/close
GET  /handoff/conversations/{shop}/{buyer}/{conversation}
```

所有请求只接受FAKE/TEST标识。操作者必须以`fake-`或`test-`开头。状态转换冲突
返回409，目录不可用返回脱敏503，输入无效返回422。响应只包含模式、原因码、
风险、队列元数据和固定提示，不回显买家文本或候选回复。

## 错误处理

- 配置缺失、未知字段、重复优先级或非法枚举：启动失败；
- SQLite忙、损坏或不可写：返回固定503，AI不发送；
- 不合法转换：409，状态、lease、队列和审计零修改；
- 重复转人工：幂等保持一个开放队列项；
- 重复领取、恢复或关闭：不伪造成功，由明确状态决定409或幂等读取；
- 高风险未确认恢复：409，owner仍为human；
- API或规则异常：不回显路径、SQL、原文或候选回复。

不自动修复数据库，不删除失败现场、SQLite或sidecar。

## 测试策略

所有测试使用临时SQLite、固定时钟和FAKE/TEST标识：

- 配置合同、规则优先级和禁止承诺；
- 至少50个独立参数化规则用例，覆盖四个验收短语、各风险类别、知识状态、
  服务故障、连续未解决和正常继续；
- 四模式合法/非法状态转换；
- 高风险恢复确认；
- 队列唯一、领取、关闭、重开和无正文审计；
- schema v1到v2迁移并保留阶段6数据；
- 人工在AI发送前接管的竞态；
- WAITING/HUMAN下新消息不发送；
- 旧epoch在重启恢复时不发送；
- API evaluate、queue、claim、resume、close和脱敏错误；
- 阶段7的95项回归继续通过。

## 明确不做

- 不接入真实客服账号、TGO Waiting Queue、TGO Visitor `ai_disabled`或浏览器工作台；
- 不调用真实模型、RAG、拼多多、订单、退款、地址或物流接口；
- 不使用真实商品、政策、买家或公司资料；
- 不实现自然语言模型分类、情感模型或自动风险学习；
- 不实现通知、排班、SLA、客服分配算法或生产权限；
- 不修改TGO核心、根Compose或依赖锁；
- 不进入阶段9实现。
