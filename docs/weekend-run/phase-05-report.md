# 阶段5报告：本地PDD消息模拟器

## 结论

阶段5自动验收为`PASS`。本阶段在
`extensions/pdd-customer-service/`内完成纯本地、进程内、合成数据驱动的PDD
消息模拟链路；没有调用真实拼多多、真实TGO业务API、模型、数据库、付费服务或
外部网络。

- 分支：`phase/05-pdd-simulator`
- 设计提交：`5e217b8`
- 计划提交：`48cfa96`
- 阶段最终提交：由安全标签`phase-05-complete^{commit}`唯一解析
- 阶段标签：`phase-05-complete`
- 主分支合并、Pull Request和强制推送：0

## 已实现范围

完整链路为：

```text
FAKE/TEST HTTP客户端
→ POST /simulator/messages
→ PddSimulatorService
→ MockPddAdapter.receive
→ NormalizedMessage
→ InMemoryConversationRepository
→ 固定回复“已收到测试消息”
→ MockPddAdapter.send
→ GET完整会话
```

实现内容：

- 六字段`PddTextMessageRequest`，标识、时区和正文边界均有校验；
- `NormalizedMessage`、`OutboundMessage`和`SimulationResult`；
- 完整`shop_id + buyer_id + conversation_id`会话键；
- 异步`PddAdapter`协议和内存`MockPddAdapter`；
- 显式禁用的`RealPddAdapter`，不含任何真实协议猜测；
- 进程内会话创建、关联和买家可见会话快照；
- 固定回复、结构化trace和不含正文的普通日志；
- FastAPI发送与查询接口；
- 单元、集成、契约和完整链路测试；
- 本地模拟器运行手册和开发范围更新。

## 明确未实现

- 真实PDD URL、Webhook、签名、加密、应答、发送协议或凭据；
- 真实TGO业务API、RAG、模型或数据库连接；
- 去重、幂等、重试、死信、持久恢复和并发串行化；
- AI与人工互斥、风险路由和人工转接；
- 正式买家页面或生产部署。

可靠性功能严格留给阶段6。阶段5进程重启后内存消息和会话会丢失。

## TDD证据

每个新增行为先观察预期RED，再写最小GREEN。关键RED包括：

- 模型、Adapter、仓库和服务尚未导入；
- 普通`datetime`错误接受无时区值；
- 普通字符串错误接受空白、空值和超长正文；
- 标识缺少长度边界；
- 模拟POST路由不存在时返回404；
- 未知会话未显式处理时返回500而非404。

完整逐项记录见
[`logs/phase-05-validation.md`](logs/phase-05-validation.md)。

最终测试结果：

| 检查 | 结果 |
|---|---|
| 单元测试 | 15项通过 |
| 集成测试 | 4项通过 |
| 契约测试 | 1项通过 |
| 全量测试 | 20项通过 |
| Ruff格式与规则 | 通过 |
| mypy strict | 27个源码文件，0问题 |
| Bandit | 通过 |
| pip-audit | 无已知漏洞 |

## 运行时验收

合成输入：

```text
你好
```

最终实际进程结果：

- 健康检查：200
- POST模拟消息：201
- Adapter入站：自动化测试证明1次
- 新建会话：`true`
- 回复：严格等于`已收到测试消息`
- GET买家会话：200
- 消息顺序：`buyer,service`
- 消息数量：2
- 日志正文匹配：0
- 验收后临时进程：已停止

第一次运行时验证发现容器内遗留的阶段3进程占用8091，导致新进程绑定失败且模拟
路由返回404。保存日志并确认进程命令和启动时间后，仅向该旧扩展进程发送
`TERM`；第二轮当前代码通过全部HTTP验收。

## 错误和修复记录

1. 计划文件Gitleaks首次封装命令因跨shell引号失败，扫描未执行；改为直接容器
   调用后扫描成功。PowerShell最初把空JSON数组误计为1，读取已保存报告后确认
   实际候选为0，没有第三次扫描。
2. 未知会话RED首次被测试客户端直接回抛响应校验异常；仅对该错误响应测试关闭
   异常回抛后，得到实际500、期望404的明确RED，再实现404分支。
3. 首轮lint报告11处`datetime.UTC`升级规则；Ruff安全机械修复后第二轮lint和
   mypy全部通过。
4. 运行时第一次验证受旧阶段3进程影响；根因确认后第二轮通过。

未解决错误：0。

## 安全与边界

- `.env`继续由`.gitignore`忽略；
- 新增依赖：0；
- 数据库迁移：0；
- TGO核心`repos/*`修改：0；
- Gitleaks完整受控源码：22项既有基线；
- Gitleaks阶段5差异：0；
- 真实密钥、真实买家数据和真实业务载荷：0；
- 候选值没有输出到对话或跟踪文档；
- 15个TGO容器保持`healthy`。

## 文件摘要

新增：

- 消息模型、PDD Adapter、会话仓库、模拟编排服务和FastAPI路由；
- 5个单元/集成测试模块和1个契约测试模块；
- 模拟器运行手册、设计、实施计划、验证日志和本报告。

修改：

- 应用工厂和依赖注入；
- 模型、Adapter、仓库和服务显式导出；
- 共享测试fixture；
- 扩展开发运行手册。

根Compose、根Makefile、依赖锁文件和`repos/*`均未修改。

## 回滚

不修改当前阶段分支，创建一个指向阶段4安全状态的新分支：

```bash
git switch -c rollback/phase-05 phase-04-complete
```

检查阶段5安全标签：

```bash
git show --stat phase-05-complete
git diff phase-04-complete..phase-05-complete
```

若只需停止本地模拟器，在运行它的终端使用`Ctrl+C`；不删除Docker卷或数据库。

## 下一阶段门禁

只有`phase-05-complete`本地和`origin`引用一致、工作区干净后，才从该标签创建
`phase/06-message-reliability`。阶段6必须新增持久状态、去重、重试、死信、
恢复和并发控制，不能把阶段5内存行为冒充为可靠性实现。
