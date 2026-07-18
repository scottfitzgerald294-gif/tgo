# 阶段5验证日志

## 执行环境

- 分支：`phase/05-pdd-simulator`
- 隔离工作树：`.worktrees/weekend-run`
- 验证容器：`pdd-weekend-verifier`
- Python：3.11.15
- Poetry：2.4.1
- 真实PDD、真实模型、TGO业务API和外部网络调用：0

## RED/GREEN证据

| 编号 | 行为 | 状态 | 命令与证据 |
|---|---|---|---|
| M01-RED | 模拟文本请求解析并规范化标识 | RED（预期） | `poetry run python -m pytest tests/unit/test_message_models.py::test_simulated_text_request_normalizes_identifiers -q`退出1；`PddTextMessageRequest`尚未导出 |
| M01-GREEN | 模拟文本请求解析并规范化标识 | GREEN | 聚焦测试和原健康单元回归共2项通过 |
| M02-RED | 拒绝无时区时间 | RED（预期） | 聚焦测试退出1；当前`datetime`类型接受了无时区值，未抛出`ValidationError` |
| M02-GREEN | 拒绝无时区时间 | GREEN | 模型测试2项全部通过 |
| M03-RED | 拒绝空白、空值和超长正文 | RED（预期） | 参数化测试3项均按预期失败；当前普通字符串未实施正文边界 |
| M03-GREEN | 拒绝空白、空值和超长正文 | GREEN | 模型测试5项全部通过 |
| M04-RED | 拒绝空白、空值和超长标识 | RED（预期） | 参数化测试3项均按预期失败；标识仅去除首尾空白，尚无长度边界 |
| M04-GREEN | 拒绝空白、空值和超长标识 | GREEN | 模型测试8项全部通过 |
| M05-RED | 完整会话键稳定且可哈希 | RED（预期） | 测试收集退出1；`ConversationKey`尚未定义和导出 |
| M05-GREEN | 完整会话键稳定且可哈希 | GREEN | 模型与原健康单元回归共10项通过 |
| M06-RED | 标准入站与出站共享追踪上下文 | RED（预期） | 测试收集退出1；`NormalizedMessage`和`OutboundMessage`尚未定义和导出 |
| M06-GREEN | 标准入站与出站共享追踪上下文 | GREEN | 模型测试10项全部通过 |
| A01-RED | Mock Adapter记录一次入站和一次出站 | RED（预期） | 测试收集退出1；`MockPddAdapter`尚未定义和导出 |
| A01-GREEN | Mock Adapter记录一次入站和一次出站 | GREEN | Adapter聚焦测试与模型回归共11项通过 |
| A02-RED | Real Adapter所有正式接口保持禁用 | RED（预期） | 测试收集退出1；`RealPddAdapter`和未配置异常尚未定义 |
| A02-GREEN | Real Adapter所有正式接口保持禁用 | GREEN | Mock Adapter与禁用契约测试共2项通过 |
| R01-RED | 会话仓库按完整键创建、复用并隔离 | RED（预期） | 测试收集退出1；`InMemoryConversationRepository`尚未定义和导出 |
| R01-GREEN | 会话仓库按完整键创建、复用并隔离 | GREEN | 模型、Adapter和仓库相关单元回归共12项通过 |
| S01-RED | 单次消息编排与脱敏追踪日志 | RED（预期） | 测试收集退出1；`FIXED_REPLY`和`PddSimulatorService`尚未定义和导出 |
| S01-GREEN | 单次消息编排与脱敏追踪日志 | GREEN | 服务聚焦测试1项通过 |
| S02-GREEN | 同一完整会话键的第二条消息复用会话 | 回归GREEN | 该行为由已先行RED验证的完整键仓库与服务直通结果组合产生；服务测试2项通过，无新增生产修改 |
| API01-RED | HTTP发送“你好”并读取固定回复 | RED（预期） | 聚焦集成测试退出1；POST当前返回404，模拟路由尚未装配 |
| API01-GREEN | HTTP发送“你好”并读取固定回复 | GREEN | 模拟完整链路与原健康接口回归共2项通过 |
| API02-RED | 未知完整会话键返回404 | RED（预期） | 首次运行由测试客户端回抛响应校验异常；仅调整该测试的异常回抛设置后，实际HTTP 500、期望404，确认缺少显式未找到分支 |
| API02-GREEN | 未知完整会话键返回404 | GREEN | 模拟接口2项与原健康接口1项全部通过 |
| API03-GREEN | 无时区时间在进入Adapter前返回422 | 回归GREEN | 时区约束已由M02先观察RED；API测试3项通过，Adapter与仓库计数保持0 |
| ALL01-GREEN | 阶段5首次全量自动化回归 | GREEN | `poetry run python -m pytest -q`共20项通过 |

## 运行时HTTP验收

首次启动前发现验证容器内已有2026-07-18 08:30启动的旧阶段3 Uvicorn进程，
占用`127.0.0.1:8091`。新进程日志明确记录`address already in use`；旧进程的
健康接口返回200，但阶段5 POST和GET均返回404。失败响应和启动日志保存在Git已
忽略的`data/weekend-run/phase-05/`，未删除失败现场。

确认PID和完整命令仅属于本扩展旧进程后发送`TERM`，再启动当前代码。第二轮结果：

| 检查 | 结果 |
|---|---|
| 健康就绪 | PASS；第8次500毫秒轮询成功 |
| POST `/simulator/messages` | PASS；HTTP 201 |
| `conversation_created` | PASS；`true` |
| 固定回复 | PASS；严格等于`已收到测试消息` |
| GET完整会话 | PASS；HTTP 200 |
| 消息数量和顺序 | PASS；2条，`buyer,service` |
| 验收后停止 | PASS；匹配进程数量为0 |

运行日志正文扫描：`你好`和`已收到测试消息`匹配数均为0；业务日志只保留固定
事件名和允许的追踪字段。

## 质量门禁

| 命令或检查 | 结果 |
|---|---|
| `make format` | PASS；Ruff格式化3个文件 |
| 首轮`make lint` | FAIL；Python 3.11升级规则要求11处使用`datetime.UTC` |
| Ruff安全自动修复 | PASS；共机械修复23项，包括UTC别名和导入整理 |
| 第二轮`make lint` | PASS；格式、Ruff和mypy strict均通过，mypy检查27个源码文件 |
| `make test-unit` | PASS；15项 |
| `make test-integration` | PASS；4项 |
| `make test` | PASS；20项，含1项禁用Real Adapter契约测试 |
| `make security-check` | PASS；Bandit通过、pip-audit无已知漏洞、`.env`保持忽略 |
| `git diff --check` | PASS |
| 阶段5占位词扫描 | PASS；0项 |
| 依赖文件变化 | PASS；`pyproject.toml`和`poetry.lock`变化0 |
| 数据库迁移 | PASS；0 |
| `repos/*`变化 | PASS；工作区和阶段提交均为0 |

## Gitleaks最终门禁

从`HEAD`只读归档叠加22个阶段5未提交文件，构造受控源码快照；另构造仅包含
阶段5差异的只读快照。扫描结果：

- 受控源码文件：1971
- 完整受控源码候选：22项既有基线
- 相对阶段4增加：0
- 阶段5差异文件候选：0
- 候选值输出：0

扫描报告、只读快照和失败现场保存在Git已忽略的
`data/weekend-run/phase-05/`。

## 容器状态

- 15个TGO容器：全部`healthy`
- `pdd-weekend-verifier`：运行中
- 阶段5临时Uvicorn进程：验收后已停止
