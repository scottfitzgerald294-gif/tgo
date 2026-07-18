# 拼多多集成边界

## 1. 边界原则

拼多多集成遵循“协议外置、业务复用、出站单点、核心最小化”的边界：

1. PDD 协议和凭据永远不进入 TGO 通用核心。
2. Visitor、Session、Staff、Queue、Agent、RAG、WuKongIM 和浏览器工作台复用 TGO。
3. PDD Connector 是所有 PDD 入站和出站的唯一进程边界。
4. 去重、防重放、回答校验、回复所有权和 PDD 审计由 Connector 强制执行，不能只依赖 Prompt。
5. 只有现有 API 无法满足明确安全要求时，才提出小而可上游合并的核心修改。

## 2. 仓库现状

- 当前仓库根目录没有 `extensions/`。
- `repos/tgo-api/app/main.py:create_app` 支持附加 Router、Middleware、启动和关闭 Hook。
- `docs-site/docs/plugin/extension-points.md` 声明了 `visitor_panel`、`chat_toolbar`、`sidebar_iframe` 和 `channel_integration`。
- `repos/tgo-plugin-runtime/app/schemas/plugin.py:PluginCapability` 允许这些能力及 `mcp_tools`。
- 插件运行时已有访客面板、工具栏、事件和工具执行的具体路由。
- `channel_integration` 当前是能力声明和文档约定，仓库中没有可直接承载高可靠渠道 Inbox、监听器和出站状态机的通用实现。
- `repos/tgo-platform/app/api/v1/messages.py:send_message` 已支持 `custom` Platform，将人工出站消息转发到 `callback_url`。

因此，PDD Connector 应是独立服务，而不是把长期运行的渠道接入逻辑塞入 UI 插件。

## 3. 建议放入 `extensions/` 的功能

未来实现阶段建议创建：

```text
extensions/
└── pdd-connector/
    ├── connector/          # 协议适配、业务编排
    ├── migrations/         # Connector 自有 Inbox/Outbox/Audit 数据
    ├── contracts/          # 与 TGO 的稳定请求/响应模型
    ├── tests/              # 协议夹具、幂等、竞态和契约测试
    ├── deploy/             # 独立服务编排覆盖，不改官方 compose 主文件
    └── README.md           # 配置、运行、故障处理
```

这一路径是目标结构，不是当前已存在目录。本阶段不会创建它。

Connector 内部职责：

| 模块 | 责任 |
|---|---|
| 官方协议 Adapter | 只依据已授权官方资料处理接收、验证、确认和发送 |
| Binding Resolver | 店铺到 TGO Project/Platform 的唯一映射 |
| Inbox | 持久接收、唯一去重、重试、死信 |
| Normalizer | 转成内部稳定领域消息 |
| TGO Client | 封装平台 API Key、Chat SSE、Visitor/Session 等调用 |
| Candidate Collector | 聚合 TGO AI 候选，不直接代表外部送达 |
| Guard | RAG 证据、输出格式、风险规则和人工转接决策 |
| Reply Lease | AI/人工原子互斥与 epoch |
| Outbox | PDD 外部发送、幂等和送达状态 |
| Audit | 追加写审计与脱敏 |

Connector 不引用 `repos/tgo-*` 的内部 Python/TypeScript 模块，不直接连 TGO 数据库。它只依赖已版本化 HTTP/SSE 契约。

## 4. 通过 TGO 现有 API 实现的功能

### 4.1 平台和访客接入

复用：

- TGO `custom` Platform 类型：`repos/tgo-api/app/models/platform.py:PlatformType.CUSTOM`
- Chat 主入口：`repos/tgo-api/app/api/v1/endpoints/chat.py:chat_completion`
- 平台 Key 到 Project 的解析、Visitor 创建、Session 和频道建立。
- 买家消息写 WuKongIM。

Connector 向 TGO 传递内部标准字段，不向 TGO 暴露 PDD 凭据或未脱敏原文。

### 4.2 AI 与知识

复用：

- `tgo-ai /api/v1/agents/run`
- Project 默认 Agent
- `AgentCollection` 与已启用 Collection
- `tgo-rag /v1/collections/{collection_id}/documents/search`
- Agent 会话 `session_id/user_id`

知识权限以 TGO Project 和 Agent Collection 绑定为准，Connector 不建立平行知识权限体系。

### 4.3 人工客服

复用：

- `/v1/visitors/{visitor_id}/accept`
- `/v1/visitors/{visitor_id}/enable-ai`
- `/v1/visitors/{visitor_id}/disable-ai`
- `/v1/sessions/visitor/{visitor_id}/close`
- `/v1/sessions/visitor/{visitor_id}/transfer`
- AI 的 `request_human_support` 与内部 `manual_service.request`
- Waiting Queue、Assignment History、Channel Member、WuKongIM 通知

浏览器工作台继续使用 `repos/tgo-web`，不为 PDD 单独开发桌面客户端。

### 4.4 人工出站

现有链路可直接复用：

```text
tgo-web
  → tgo-api POST /v1/chat/messages/send
  → tgo-platform POST /v1/messages/send
  → custom Platform callback_url
  → PDD Connector
  → 回答租约与 Outbox
  → PDD 官方发送通道
```

证据：

- `repos/tgo-web/src/services/chatMessagesApi.ts:staffSendPlatformMessage`
- `repos/tgo-api/app/api/v1/endpoints/chat.py:staff_send_platform_message`
- `repos/tgo-platform/app/api/v1/messages.py:send_message`

`tgo-api` 在转发前校验客服权限、频道类型、Channel Member、Visitor Project 和 Platform 状态。Connector 再执行外部会话租约和 PDD 出站幂等。

## 5. 由 Connector 实现、不能委托给 TGO 的功能

| 功能 | 原因 |
|---|---|
| PDD 请求验证和应答 | 属于外部平台协议，TGO 当前没有实现，且不能猜测 |
| PDD 凭据生命周期 | 凭据应只存在于最小信任域 |
| PDD 事件去重与防重放 | 现有 Inbox 为其他渠道专用，Chat 入口没有外部事件唯一键 |
| PDD 标识映射 | 外部店铺、买家、会话语义属于 Connector |
| PDD Outbox 和送达状态 | TGO 的 WuKongIM 消息不等于 PDD 送达 |
| 回答校验和风险规则 | 必须在 PDD 出站前强制执行 |
| AI/人工回复租约 | 现有 `ai_disabled` 不能原子覆盖所有外部出站竞态 |
| PDD 审计链 | 需要关联验证、策略、租约和外部发送结果 |

## 6. 可能需要的最小核心修改

第一版可以在受控内部网络中利用 `custom` Platform 完成主链，不要求修改官方默认分支。以下修改只有在对应上线条件成立时才进入单独阶段和独立 PR。

### 6.1 `custom` 回调的服务身份

当前 `repos/tgo-platform/app/api/v1/messages.py:send_message` 对 `callback_url` 发起 POST，但没有标准 Authorization Header。

生产环境若不能由服务网格或反向代理提供双向身份验证，最小修改为：

- 在 Platform config 中保存 Secret 引用而不是明文 Token。
- 出站时解析引用并附加 `Authorization` 或专用签名 Header。
- 日志屏蔽 Header 和 Secret。
- 只修改 custom 分支，不影响其他 Adapter。

该修改解决 TGO Platform 到 Connector 的调用认证，不实现任何 PDD 协议。

### 6.2 候选回答与外部送达状态

当前 `chat_completion` 会把 AI 流写入 WuKongIM，工作台无法从消息本身区分“AI 候选”“Guard 已批准”“PDD 已送达”。

若运营验收要求在 TGO 工作台中展示该状态，最小修改为：

- 允许 Connector 通过稳定事件接口回写 `candidate/approved/delivered/rejected` 状态。
- 状态放在消息 `extra` 或独立集成状态记录中，不改变消息正文。
- 新字段全部可选，旧客户端忽略后仍可运行。

第一版即使不增加 UI 状态，PDD 真实送达仍只以 Connector Outbox 为准。

### 6.3 外部入站幂等键透传

Connector 已能在调用 TGO 前去重。若还要求 TGO 自身对调用方重试提供第二层幂等，可最小增加：

- Chat 请求接受调用方生成的 `ingress_idempotency_key`。
- 以 Platform 和 Key 唯一落库。
- 已成功的 Key 返回原处理结果，不重复写 WuKongIM 或触发 AI。

该修改是纵深防御，不取代 Connector Inbox。

### 6.4 统一回复所有权 Hook

第一版所有 PDD 出站均经过 Connector，因此租约可完全在 Connector 执行。只有当未来出现其他合法 PDD 出站路径时，才需要在 TGO 发送前增加通用授权 Hook。Hook 应返回 allow/deny 和原因码，不把 PDD 逻辑写入 TGO。

## 7. 明确不修改的核心区域

- 不在 `repos/tgo-api` 写 PDD 签名或字段解析。
- 不在 `repos/tgo-platform/app/api/v1/callbacks.py` 复制未经确认的 PDD Webhook。
- 不在 `repos/tgo-ai` 写店铺凭据或 PDD 发送工具。
- 不在 `repos/tgo-rag` 保存订单实时数据。
- 不修改 WuKongIM 协议。
- 不在 `repos/tgo-web` 运行模型或保存 PDD Secret。
- 不把 Connector 表加入 TGO 服务迁移。

## 8. 避免上游升级冲突

### 8.1 代码边界

- Connector 使用独立目录、独立镜像、独立数据库 schema 和独立版本号。
- 通过 Compose override 或额外部署清单接入，不直接改 `docker-compose.yml` 的官方服务定义。
- 所有 TGO 调用集中在 Connector 的 `TGO Client`，业务模块不散落 HTTP 调用。
- 不 import TGO 内部模块，不复制 TGO ORM 模型。

### 8.2 契约边界

- 固定并记录使用的 TGO API 路径、方法、认证、必需字段和 SSE 事件。
- 对 Chat SSE、AI disabled、queued、custom callback 建立契约测试。
- 未知响应字段忽略；必需字段缺失时停止自动回复并转人工。
- 每次合并 upstream 前对契约测试、幂等测试和人工/AI 竞态测试重新运行。

### 8.3 Git 边界

- 官方跟踪分支只从 `upstream` 更新，不直接提交 PDD 代码。
- 集成分支为 `pdd-customer-service`。
- 每一阶段使用 `phase/*` 分支和阶段标签。
- 必须修改核心时，每个最小修改使用独立提交，便于在上游已提供同等能力后单独删除。

### 8.4 配置边界

- TGO Platform config 只保留 Connector 路由和非敏感绑定引用。
- PDD Secret、模型 Secret 和 TGO Platform API Key 使用 Secret Store 引用。
- 开发、测试、生产使用不同绑定、凭据和审计保留策略。
- 自动回复用显式功能开关按店铺启用，默认关闭。

## 9. 边界验收

- 删除 Connector 不影响 TGO 其他渠道运行。
- 升级 TGO 时不需要手工合并 PDD 协议代码。
- Connector 无法直接写 TGO 表。
- TGO Web 和客服浏览器无法读取 PDD Secret。
- PDD 外部发送只能从 Connector 出口发生。
- 核心修改若出现，能够按独立提交回退且不破坏 Connector 的人工模式。
