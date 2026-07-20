# 本地PDD消息模拟器运行手册

## 适用范围

本手册只适用于阶段5的本地合成消息链路。所有示例店铺、买家、会话、消息ID和
文本均为`FAKE/TEST`数据。服务不访问真实拼多多、TGO业务API、模型、数据库、
浏览器账号或外部网络，也不需要任何真实凭据。

`RealPddAdapter`保持显式未配置；调用其任一正式接口都会抛出
`RealPddNotConfiguredError`，不会尝试网络请求或猜测拼多多协议。

## 启动、检查与停止

从扩展目录执行：

```bash
cd extensions/pdd-customer-service
make run
```

服务只绑定：

```text
http://127.0.0.1:8091
```

健康检查：

```bash
curl --fail http://127.0.0.1:8091/health
```

预期：

```json
{"status":"healthy","service":"pdd-customer-service"}
```

前台运行时使用`Ctrl+C`停止。不要用强制终止、删除容器、删除卷或清理数据库的
方式停止本模拟器。

若使用现有验证容器：

```bash
docker exec -w /repo/extensions/pdd-customer-service \
  pdd-weekend-verifier make run
```

## 发送一条合成买家消息

### curl

```bash
curl --fail --request POST \
  --header "Content-Type: application/json" \
  --data '{
    "message_id": "message-001",
    "shop_id": "shop-test",
    "buyer_id": "buyer-test",
    "conversation_id": "conversation-test",
    "timestamp": "2026-07-18T09:00:00Z",
    "content": "你好"
  }' \
  http://127.0.0.1:8091/simulator/messages
```

预期HTTP状态为`201`，且响应中的固定回复严格为：

```text
已收到测试消息
```

### PowerShell

```powershell
$body = @{
    message_id = "message-001"
    shop_id = "shop-test"
    buyer_id = "buyer-test"
    conversation_id = "conversation-test"
    timestamp = "2026-07-18T09:00:00Z"
    content = "你好"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8091/simulator/messages" `
    -ContentType "application/json" `
    -Body $body
```

不要把真实店铺、买家、订单、地址、凭据或生产消息替换进这些示例。

## 查询完整会话

完整会话键必须同时包含店铺、买家和会话ID：

```bash
curl --fail \
  http://127.0.0.1:8091/simulator/shops/shop-test/buyers/buyer-test/conversations/conversation-test
```

成功时返回两条有序消息：

1. `buyer`：`你好`
2. `service`：`已收到测试消息`

未知完整会话键返回`404`和：

```json
{"detail":"Conversation not found"}
```

缺字段、无时区时间、空正文或超长正文返回`422`，且不会进入Adapter或创建会话。

## 状态与阶段边界

- Adapter消息和会话关联只保存在当前Python进程内存中。
- 服务重启后模拟会话会丢失；这是阶段5的明确限制。
- 阶段5不对重复`message_id`去重，同一HTTP请求只保证调用一次入站处理。
- 去重、幂等、重试、死信、持久恢复和会话并发控制属于阶段6。
- 本阶段没有正式业务界面；HTTP接口和自动化测试客户端即模拟买家入口。

## 日志与脱敏

业务日志事件只有：

```text
mock_pdd_message_received
mock_pdd_reply_sent
```

允许记录的追踪字段为`trace_id`、`message_id`、`conversation_id`和`direction`。
普通日志不得记录正文、完整外部负载、店铺凭据、模型Key或真实个人数据。若保存
运行日志，应放入Git已忽略的`data/`或`logs/`目录。

## 故障排查

### 8091端口已被占用

先识别进程，不要直接批量终止：

```bash
pgrep -af "uvicorn app.main:app --host 127.0.0.1 --port 8091"
```

若确认是本扩展的旧本地进程，先正常停止旧进程，再重新执行`make run`。不得终止
未确认的进程。

### POST返回404

确认运行的是当前阶段5代码，而不是只提供`/health`的旧阶段3进程；重新启动后再
检查OpenAPI是否包含`/simulator/messages`。

### POST返回422

检查六个字段是否齐全，`timestamp`是否带时区，标识是否非空且不超过128字符，
正文去除首尾空白后是否为1至4000字符。

### 未知会话返回404

查询路径中的`shop_id`、`buyer_id`和`conversation_id`必须与POST完全一致。
