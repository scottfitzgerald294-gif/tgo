# 阶段7验证日志

## 执行环境

- 分支：`phase/07-knowledge-framework`
- 阶段起点：`phase-06-complete`（`9bfda13`）
- 验证容器：`pdd-weekend-verifier`
- Python：3.11.15
- Poetry：2.4.1
- 真实公司资料、真实PDD、真实模型、TGO业务API和外部网络调用：0

## RED/GREEN证据

| 编号 | 行为 | 状态 | 命令与证据 |
|---|---|---|---|
| M01-RED | 七类知识和统一治理字段 | RED（预期） | 测试收集失败；知识枚举与记录模型尚不存在 |
| M01-GREEN | 七类知识和统一治理字段 | GREEN | 模型参数化10项通过；无时区、倒置时间和approved无审核者均拒绝 |
| CSV01-RED | 固定表头、严格字段与精确摘要 | RED（预期） | 服务与CSV合同尚不存在 |
| CSV01-GREEN | 固定表头、严格字段与精确摘要 | GREEN | 缺表头、有效行、摘要字节稳定性3组通过；预览零写入 |
| CSV02-RED | 来源、批内/目录重复和安全warning | RED（预期） | 预览未产生所需问题码 |
| CSV02-GREEN | 来源、批内/目录重复和安全warning | GREEN | CSV预览5组通过；error与warning计数分离 |
| DB01-RED | JSON初始化、原子导入与重开 | RED（预期） | JSON仓库接口尚不存在 |
| DB01-GREEN | JSON初始化、原子导入与重开 | GREEN | 构造零写入，显式初始化、两版本导入和重开通过 |
| DB02-RED | 重复批次、损坏JSON和未知schema保留现场 | RED（预期） | 缺少原子重复拒绝和脱敏持久化异常 |
| DB02-GREEN | 重复批次、损坏JSON和未知schema保留现场 | GREEN | 仓库4项通过；失败前后目录不变且错误不含路径/正文 |
| SV01-RED | 正式导入摘要绑定与阻断错误零写入 | RED（预期） | 正确数据路径对非运行时Protocol执行`isinstance`并抛`TypeError` |
| SV01-GREEN | 正式导入摘要绑定与阻断错误零写入 | GREEN | 根因是Protocol缺少`@runtime_checkable`；最小修复后聚焦测试1项通过 |
| SV02-RED | 自动回答资格矩阵 | RED（预期） | `eligible_records`尚不存在，12项按预期失败 |
| SV02-GREEN | 自动回答资格矩阵 | GREEN | 草稿、撤回、未审核、拒绝、无效来源、未来、过期、高风险、禁用、禁止回答和转人工均排除；活动版本正例通过，共13项 |
| SV03-RED | 活动知识冲突与非冲突矩阵 | RED（预期） | 两条冲突知识均被错误返回；修正一次测试关键字重复后稳定复现1项真实失败 |
| SV03-GREEN | 活动知识冲突与非冲突矩阵 | GREEN | 冲突双方排除；内容相同、类别不同、三层作用域分离、时间分离、未发布和未审核8类不误判，共9项 |
| CSV03-RED | 批内及活动目录冲突预警 | RED（预期） | 两种预览均缺少`knowledge_conflict` |
| CSV03-GREEN | 批内及活动目录冲突预警 | GREEN | 两项聚焦测试通过；只为CSV中的冲突记录生成无正文warning |
| DB03-RED | 无删除回滚与失败原子性 | RED（预期） | JSON仓库尚无`rollback` |
| DB03-GREEN | 无删除回滚与失败原子性 | GREEN | 两项通过；历史保留、活动指针切换、无正文审计，不存在/已活动目标零修改 |
| SV04-RED | 服务回滚和合成操作者边界 | RED（预期） | 服务尚无`rollback` |
| SV04-GREEN | 服务回滚和合成操作者边界 | GREEN | 服务/仓库/阶段6可靠性回归41项通过；回滚后资格立即使用目标版本 |
| CLI01-RED | CLI安全预览 | RED（预期） | `scripts.knowledge_catalog`尚不存在 |
| CLI01-GREEN | CLI安全预览 | GREEN | 聚焦测试1项通过；输出无正文和绝对路径 |
| CLI02-RED | CLI正式导入、资格与回滚 | RED（预期） | argparse只有preview子命令，两项按预期失败 |
| CLI02-GREEN | CLI正式导入、资格与回滚 | GREEN | 3项集成测试通过；摘要错误退出2且零写入，活动版本与回滚输出正确 |
| ASSET01-RED | 固定模板和七类虚构样例 | RED（预期） | 跟踪的CSV资产不存在 |
| ASSET01-GREEN | 固定模板和七类虚构样例 | GREEN | CLI/资产集成4项通过；16列表头、七类、FAKE来源和禁用类别全部锁定 |
| ASSET02-RED | 样例提供可回滚双版本 | RED（预期） | FAKE商品样例只有v1 |
| ASSET02-GREEN | 样例提供可回滚双版本 | GREEN | 增加明确禁用自动回答的FAKE v2后资产测试通过 |
| CLI03-RED | 直接脚本进程入口 | RED（预期） | 真实子进程退出1；脚本目录成为`sys.path[0]`，无法导入同级`app` |
| CLI03-GREEN | 直接脚本进程入口 | GREEN | 仅直接执行模式加入扩展根目录；真实子进程测试通过，模块导入模式不改路径 |

## 调试记录

1. 正式导入首次GREEN失败稳定复现为Python `TypeError`。调用栈定位到
   `isinstance(repository, KnowledgeRepository)`；协议结构正确但未声明
   `@runtime_checkable`。第一轮根因分析后只添加装饰器和返回类型，聚焦测试通过。
2. 冲突矩阵首次RED包含一处测试数据构造错误：`content`关键字被传入两次。该
   错误没有触发生产修改；只合并测试更新映射后重新运行，得到唯一真实冲突失败，
   随后实现冲突规则并通过。
3. 首次实际CLI验收的嵌套shell命令被Windows/PowerShell/容器三层引号截断，
   没有创建目录或进入业务。改成逐条进程调用后发现直接脚本入口无法导入`app`；
   新增真实子进程RED，定位`sys.path[0]`后最小修复并通过。
4. 首轮lint发现`scripts/`缺少包标记，mypy把同一文件识别为两个模块；增加
   `scripts/__init__.py`后，下一轮发现导入与回滚分支复用`result`导致类型收窄
   错误。使用`import_result/rollback_result`明确类型后通过。

每个错误均在两轮限制内解决；没有删除测试、降低断言、关闭检查、忽略异常或
硬编码成功结果。

## 实际CLI验收

使用Git忽略的`.local/phase07-acceptance-v1.json`和跟踪的八条FAKE记录：

| 检查 | 结果 |
|---|---|
| preview | PASS；8条、0 error、4 warning |
| SHA-256绑定正式导入 | PASS；导入8条、7个活动ID |
| 回滚前eligible | PASS；4条，禁用的商品v2被排除 |
| 回滚商品到v1 | PASS；活动指针`2 -> 1` |
| 新进程重开eligible | PASS；5条，商品v1恢复资格 |
| CLI输出正文或绝对路径 | 0 |

目录和首次失败现场均保留在Git忽略的`.local/`中，没有删除或覆盖。

## 最终质量门禁

| 命令或检查 | 结果 |
|---|---|
| `make format` | PASS；48个Python源码无需变化 |
| `make lint` | PASS；Ruff通过，mypy strict检查48个源码文件、0问题 |
| `make test-unit` | PASS；82项 |
| `make test-integration` | PASS；12项 |
| `make test` | PASS；95项，含1项Real Adapter禁用契约 |
| `make security-check` | PASS；Bandit、pip-audit和`.env`忽略检查通过 |
| `git diff --check` | PASS |
| `repos/*`工作区和阶段差异 | PASS；0 |
| 依赖及锁文件变化 | PASS；0 |
| 知识目录与`.env`忽略 | PASS |
| TGO核心容器 | PASS；15个均`healthy` |

## Gitleaks门禁

- 完整受控源码文件：2021；
- 阶段7完整候选：22；
- 阶段6完整基线：22；
- 按规则ID和去除快照前缀后的相对文件路径归一化比较：新增0、移除0；
- 候选值输出：0；
- 扫描源和报告保存在Git忽略的`data/weekend-run/phase-07/`，失败现场未删除。
