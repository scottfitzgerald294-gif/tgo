# 本地消息可靠性运行手册

## 适用范围

本手册仅适用于
`extensions/pdd-customer-service/`中的阶段6本地模拟链路。所有消息、店铺、
买家、会话和SQLite数据必须明确为`FAKE/TEST`。本实现不访问真实拼多多、真实
TGO业务API、真实模型、生产数据库、付费服务或外部网络，也不声称
`shop_id + message_id`是真实拼多多幂等协议。

阶段6使用扩展自有SQLite Inbox/Outbox/Audit账本。它适合单Connector进程的本地
验证；多副本分布式锁、生产数据库、真实Webhook签名和官方幂等合同不在本阶段
范围内。

## 配置与Schema初始化

默认数据库位置：

```text
extensions/pdd-customer-service/.local/pdd-reliability.sqlite3
```

该文件及SQLite sidecar由根`.gitignore`中的`*.sqlite3`规则忽略。可在本地
`.env`或进程环境中设置空安全变量：

```text
PDD_RELIABILITY_DB_PATH=
```

只能填写本地开发路径，不得填写生产数据库、网络URL、凭据或真实业务目录。
应用导入时不创建文件；FastAPI lifespan启动时才：

1. 创建数据库父目录；
2. 执行`app/repositories/sql/001_reliability.sql`；
3. 设置并验证`PRAGMA user_version=1`；
4. 扫描到期、可重试且未完成的Outbox。

启动前确认忽略规则：

```bash
git check-ignore -v \
  extensions/pdd-customer-service/.local/pdd-reliability.sqlite3
```

## 启动、健康检查与停止

```bash
cd extensions/pdd-customer-service
make run
```

健康检查：

```bash
curl --fail http://127.0.0.1:8091/health
```

预期：

```json
{"status":"healthy","service":"pdd-customer-service"}
```

前台运行时使用`Ctrl+C`正常停止。若后台运行，必须先确认完整命令和PID只属于本
扩展，再向该PID发送`TERM`。不得批量终止进程，不得删除SQLite文件、Docker卷或
数据库，不得使用`docker compose down -v`。

## 发送与查询FAKE/TEST消息

`timestamp`必须带时区，并位于当前UTC时间向前300秒、向后60秒的允许窗口内：

```bash
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
curl --fail --request POST \
  --header "Content-Type: application/json" \
  --data "{
    \"message_id\":\"message-test-001\",
    \"shop_id\":\"shop-test\",
    \"buyer_id\":\"buyer-test\",
    \"conversation_id\":\"conversation-test\",
    \"timestamp\":\"${NOW}\",
    \"content\":\"你好\"
  }" \
  http://127.0.0.1:8091/simulator/messages
```

首次成功为HTTP 201、`duplicate=false`、`processing_status=sent`。相同
`shop_id + message_id`再次提交仍为201，但`duplicate=true`，不会重复调用
Adapter、创建会话或发送回复。

查询：

```bash
curl --fail \
  http://127.0.0.1:8091/simulator/shops/shop-test/buyers/buyer-test/conversations/conversation-test
```

成功交付的单条消息应只有一条`buyer`和一条`service`。过期或未来消息返回409；
账本不可用返回脱敏503；未知会话返回404；输入校验失败返回422。

## 状态、重试和死信

| 状态 | 含义 | 是否自动恢复 |
|---|---|---|
| `pending` | Inbox和Outbox已原子创建，尚未发送 | 是 |
| `failed` | 最近一次发送失败，原因已审计 | 仅`retryable=true` |
| `retrying` | 已安排下一次尝试 | 到期后是 |
| `sent` | 固定reply已成功交付 | 否 |
| `dead_letter` | 达到最大尝试次数 | 否 |

默认策略：

- 最多3次发送尝试；
- 退避为1秒、2秒，之后按指数增长但不超过30秒；
- 单次发送超时2秒；
- 同一完整会话串行，不同完整会话允许并行；
- 每次发送复用同一`reply_id`；
- 每次外发前复核AI owner与epoch。

Mock Adapter可以在测试中配置前N次固定失败；它按`reply_id`保证买家视图最多
出现一条回复。达到最大尝试后进入`dead_letter`，不会自动重发。

## 重启恢复

正常启动会扫描：

```text
status in (pending, failed, retrying)
AND retryable = true
AND next_attempt_at为空或已到期
```

恢复沿用持久化的trace、reply、attempts和lease epoch，不重新Claim，不重复记录
入站，不恢复`sent`、`dead_letter`或human阻止项。若旧任务被取消，
`CancelledError`不会被吞掉，账本现场保留供下一进程恢复。

## AI与人工回复所有权

阶段6只实现最小租约，不是阶段8完整人工转接状态机：

```text
owner = ai | human
epoch = 单调递增整数
```

- human已持有时，新AI处理标为不可重试`failed`且不调用Adapter；
- human接管会使旧AI epoch失效；
- 每次外发前发现epoch失效时停止发送并审计`reply_lease_changed`；
- 返回AI必须调用显式release操作；AI不能自行覆盖human。

## 审计、日志与隐私

`audit_events`只追加，保存trace、事件、状态、attempt、固定原因码和时间，不保存
消息正文。普通fallback日志事件固定为：

```text
reliability_database_unavailable
```

允许的附加字段只有脱敏trace、operation和`database_unavailable`原因。日志不得
包含正文、SQL、绝对数据库路径、真实店铺/买家资料、凭据或模型Key。

数据库不可用时：

1. Claim失败则不调用Adapter；
2. 处理中途失败则立即停止，不调用发送接口；
3. HTTP返回503；
4. 保留SQLite和日志现场，不自动修复或删除。

## 只读检查与备份

只读查看Schema版本：

```bash
python -c \
  "import sqlite3; c=sqlite3.connect('file:.local/pdd-reliability.sqlite3?mode=ro', uri=True); print(c.execute('PRAGMA user_version').fetchone()[0])"
```

备份前先正常停止扩展进程，再使用操作系统的普通文件复制功能复制数据库及当时
存在的`-wal`、`-shm` sidecar到Git忽略的备份目录。不得在本手册中执行或推荐
删除数据库、清空表、删除卷或破坏性回滚。

## 故障诊断

### HTTP 409

检查客户端UTC时间；默认允许窗口为过去300秒和未来60秒。不要放宽窗口来掩盖
时钟错误。

### HTTP 503

检查数据库父目录是否可写、磁盘空间、文件锁和启动日志中的固定fallback事件。
不要把SQL、绝对路径或消息正文复制到共享报告。

### `dead_letter`

按trace读取不含正文的审计顺序，确认`send_failed`原因和attempts。阶段6没有
自动死信重放命令；保留现场并由人工决定后续，不修改状态或删除记录。

### human阻止

确认完整会话键与当前owner。只有明确的本地release操作可以生成新AI epoch；
不得让AI自动恢复human会话。

### 单进程限制

`ConversationLockRegistry`仅提供单Python进程会话锁，SQLite也按单Connector进程
设计。不得把本实现直接作为多副本生产方案；分布式锁和生产账本属于阶段9以后
准备项。
