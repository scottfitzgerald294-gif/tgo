# 阶段6验证日志

## 执行环境

- 分支：`phase/06-message-reliability`
- 阶段起点：`phase-05-complete`（`2700f73`）
- 验证容器：`pdd-weekend-verifier`
- Python：3.11.15
- Poetry：2.4.1
- 真实PDD、真实模型、TGO业务API和外部网络调用：0

## RED/GREEN证据

| 编号 | 行为 | 状态 | 命令与证据 |
|---|---|---|---|
| M01-RED | 指数退避并受最大延迟限制 | RED（预期） | 测试收集退出1；`RetryPolicy`尚未定义和导出 |
| M01-GREEN | 指数退避并受最大延迟限制 | GREEN | 聚焦测试1项通过 |
| M02-RED | 重放窗口和未来时钟边界 | RED（预期） | 聚焦测试退出1；`timestamp_reason`尚不存在 |
| M02-GREEN | 重放窗口和未来时钟边界 | GREEN | 可靠性模型测试2项通过 |
| M03-RED | 可靠性状态和回复所有权值稳定 | RED（预期） | 测试收集退出1；`MessageStatus`和`ReplyOwner`尚未导出 |
| M03-GREEN | 可靠性状态和回复所有权值稳定 | GREEN | 修正一次测试断言插入位置后，可靠性模型与阶段5模型回归共13项通过 |
| M04-RED | 阶段5结果获得向后兼容可靠性默认字段 | RED（预期） | 聚焦测试退出1；`SimulationResult`缺少`processing_status`、`duplicate`和`attempts` |
| M04-GREEN | 阶段5结果获得向后兼容可靠性默认字段 | GREEN | 可靠性模型、阶段5模型和服务回归共16项通过 |
| DB01-RED | SQLite账本原子Claim同一消息一次 | RED（预期） | 测试收集退出1；`SQLiteReliabilityStore`尚未定义和导出 |
| DB01-GREEN | SQLite账本原子Claim同一消息一次 | GREEN | 聚焦测试1项通过；重复请求保留首次trace、reply和回复正文 |
| DB02-RED | 状态、审计、重开和持久会话 | RED（预期） | 聚焦测试退出1；缺少`mark_inbound_recorded` |
| DB02-GREEN | 状态、审计、重开和持久会话 | GREEN | 修正测试对返回类型的一处错误引用后，仓库测试2项通过 |
| DB03-RED | 持久reply epoch与到期恢复查询 | RED（预期） | 聚焦测试退出1；缺少`acquire_ai_lease` |
| DB03-GREEN | 持久reply epoch与到期恢复查询 | GREEN | 聚焦测试1项通过；human使旧AI epoch失效，显式release递增epoch，仅返回到期可重试记录 |
| AD01-RED | Mock发送失败注入和reply幂等 | RED（预期） | 测试收集退出1；`MockPddSendError`尚未定义和导出 |
| AD01-GREEN | Mock发送失败注入和reply幂等 | GREEN | 聚焦测试1项通过；4次调用含前2次失败，买家视图仅1条成功回复 |
| AD02-RED | Mock入站`shop_id + message_id`幂等 | RED（预期） | 聚焦测试失败；重复receive使`inbound_count`达到10 |
| AD02-GREEN | Mock入站`shop_id + message_id`幂等 | GREEN | Adapter单元测试3项通过；10次重复入站仅保存1条buyer消息 |
| SV01-RED | 10次重复消息只处理一次 | RED（预期） | 测试收集退出1；`ReliablePddSimulatorService`尚未定义和导出 |
| SV01-GREEN | 10次重复消息只处理一次 | GREEN | 聚焦测试1项通过；Adapter入站/出站与会话仓库均只执行一次，后9次持久短路 |
| SV02-RED | 前两次失败、第三次成功 | RED（预期） | 聚焦测试失败；构造函数尚不接受`retry_policy` |
| SV02-GREEN | 前两次失败、第三次成功 | GREEN | 聚焦测试1项通过；虚拟退避为1秒/2秒，3次尝试仅交付1条回复，失败与成功均有审计 |
| SV03-RED | 达到最大尝试进入dead_letter | RED（预期） | 聚焦测试失败；第3次模拟失败仍向上抛出 |
| SV03-GREEN | 达到最大尝试进入dead_letter | GREEN | 死信与两失败一成功回归共2项通过；最终失败和dead_letter均有审计 |
| SV04-RED | 发送超时安全进入dead_letter | RED（预期） | 服务未应用0.01秒策略超时，测试由0.2秒外部护栏取消并失败 |
| SV04-GREEN | 发送超时安全进入dead_letter | GREEN | 可靠服务测试4项通过；内部超时原因`send_timeout`落入失败与死信审计 |
| SV05-RED | 会话级串行且不同会话并行 | RED（预期） | 不同会话并行通过；同会话第二条在首条释放前进入发送，聚焦组1通过1失败 |
| SV05-GREEN | 会话级串行且不同会话并行 | GREEN | 可靠服务测试6项通过；不同会话最大并发2，同会话最大并发1且顺序稳定 |
| SV06-RED | human所有权阻止AI直到显式释放 | RED（预期） | 聚焦测试失败；可靠服务尚无`take_human_ownership` |
| SV06-GREEN | human所有权阻止AI直到显式释放 | GREEN | 聚焦测试1项通过；阻止项不可重试且Adapter零调用，显式release后新消息成功 |
| SV07-RED | human接管使旧AI epoch失效 | RED（预期） | 聚焦测试失败；接管发生后旧AI仍发送并落为sent |
| SV07-GREEN | human接管使旧AI epoch失效 | GREEN | 可靠服务测试8项通过；每次外发前复核owner与epoch，旧AI零发送并记录不可重试失败 |
| SV08-RED | 重放窗口先于持久化拒绝旧消息 | RED（预期） | 测试收集退出1；`ReplayWindowError`尚未定义和导出 |
| SV08-GREEN | 重放窗口先于持久化拒绝旧消息 | GREEN | 聚焦测试1项通过；超窗请求未写Inbox且Adapter零调用 |
| SV09-RED | 取消旧任务后从同一SQLite恢复 | RED（预期） | 取消后保留retrying现场；新服务缺少`recover_pending` |
| SV09-GREEN | 取消旧任务后从同一SQLite恢复 | GREEN | 聚焦测试1项通过；从attempt 2和同一reply继续，最终只交付1条，持久会话2条 |
| SV10-RED | Claim数据库不可用时零副作用 | RED（预期） | 测试收集退出1；`ReliabilityUnavailableError`尚未定义和导出 |
| SV10-GREEN | Claim数据库不可用时零副作用 | GREEN | 聚焦测试1项通过；固定脱敏日志、Adapter零调用，同消息下一次可成功 |
| SV11-RED | 处理中途数据库故障停止外发 | RED（预期） | `mark_inbound_recorded`故障直接泄漏底层异常 |
| SV11-GREEN | 处理中途数据库故障停止外发并恢复 | GREEN | 首次GREEN证明发送调用保持0且日志脱敏；补充恢复断言先RED于会话仓库为0，修复后聚焦故障与重启恢复2项通过，补齐buyer/service持久会话 |
| API01-RED | 默认可靠API、201/409/503和持久GET | RED（预期） | 3项集成测试均失败；`create_app`尚不接受`reliability_store` |
| API01-GREEN | 默认可靠API、201/409/503和持久GET | GREEN | 修正一次`RetryPolicy`导入位置后，3项集成测试全部通过 |
| ALL01-GREEN | 阶段6最终自动化回归 | GREEN | 单元36项、集成7项、契约1项，共44项通过 |

## 实际进程验收

使用验证容器、真实Uvicorn进程、端口18091和Git忽略的
`.local/phase06-acceptance.sqlite3`：

| 检查 | 结果 |
|---|---|
| 健康检查 | PASS |
| 相同消息POST 10次 | PASS；首次1次，重复9次 |
| 首次状态 | `sent`、`duplicate=false` |
| 重复状态 | 均`duplicate=true` |
| 重启前会话 | 2条，`buyer,service` |
| 正常停止并关闭端口 | PASS |
| 同一SQLite重启 | PASS |
| 重启后会话 | 与重启前完全一致 |
| 最终端口 | 关闭 |

首个HTTP循环命令因Windows、PowerShell和容器shell的多层引号被截断，没有触达
业务。保留失败现场，改用内存Base64传递相同脚本后通过。Uvicorn均收到`TERM`，
但验证容器PID 1没有回收已退出的子进程，保留两个`defunct`条目；端口已关闭，
不存在运行中的扩展服务。

## 质量门禁

| 命令或检查 | 结果 |
|---|---|
| `make format` | PASS；37个Python源文件保持格式化 |
| 首轮`make lint` | FAIL；5个文件需格式化 |
| 第二轮`make lint` | FAIL；Ruff机械修复3项后，mypy发现测试fixture模块名重复 |
| 第三轮`make lint` | FAIL；补测试包标记后，mypy报告7个显式类型收窄问题 |
| 最终`make lint` | PASS；Ruff通过，mypy strict检查37个源码文件、0问题 |
| `make test-unit` | PASS；36项 |
| `make test-integration` | PASS；7项 |
| `make test` | PASS；44项，含1项Real Adapter禁用契约 |
| `make security-check` | PASS；Bandit、pip-audit和`.env`忽略检查通过 |
| `git diff --check` | PASS |
| `repos/*`工作区和阶段差异 | PASS；0 |
| 依赖与锁文件变化 | PASS；0 |
| SQLite及sidecar忽略 | PASS |
| TGO核心容器 | PASS；15个均`healthy` |

## Gitleaks门禁

最终受控快照结果：

- 完整受控源码文件：2003；
- 完整候选：22项，等于阶段5既有基线；
- 阶段6差异文件：28；
- 差异快照候选：1项；
- 该1项定位到扩展`.env.example`既有空变量模板，变量名、空值长度和上下文与
  阶段5基线完全相同，仅因本阶段在其上方增加两行本地SQLite说明而行号移动；
- 阶段6新增候选：0；
- 候选值输出：0。

第一轮扫描封装因PowerShell反斜杠正则转换失败，未生成报告，不能作为结果。
第二轮复用已保存快照并验证容器退出码与报告存在性后得到上述结果。报告和受控
快照保存在Git忽略的`data/weekend-run/phase-06/`，未删除失败现场。
