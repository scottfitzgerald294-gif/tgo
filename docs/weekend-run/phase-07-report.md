# 阶段7报告：知识数据框架

## 结论

阶段7自动验收为`PASS`。本阶段只实现扩展自有、单进程、本地JSON知识治理，
所有样例均明确为`FAKE/TEST`；没有调用真实拼多多、真实TGO业务API、TGO RAG、
真实模型、生产数据、公司资料、外部网络或付费服务。

- 分支：`phase/07-knowledge-framework`
- 设计提交：`411687c`
- 计划提交：`b3dfd8b`
- 阶段最终提交：由`phase-07-complete^{commit}`唯一解析
- 阶段标签：`phase-07-complete`
- 主分支合并、Pull Request和强制推送：0

## 已实现范围

数据治理流：

```text
FAKE/TEST CSV
→ 固定合同与类型校验
→ 精确字节SHA-256预览
→ error阻断 / warning保留
→ 原子JSON不可变版本
→ 活动版本与无正文审计
→ 作用域、时间、风险和冲突资格
→ 合格ID列表或安全排除
→ 显式无删除回滚
```

实现内容：

- 七类知识：商品、SKU、FAQ、发货物流、售后、禁止回答、转人工条件；
- 用户要求的13个治理字段及`kind/title/content`；
- 固定16列UTF-8 CSV、严格布尔/时间/空字段处理和精确摘要；
- 批内/目录重复、无效来源、未发布、未审核、过期、未来、高风险、禁用和冲突
  问题码；
- 同类别、正文不同、三层作用域重叠、时间重叠、双方已发布且已审核的确定性
  冲突规则；
- 只有活动版本可参与的自动回答资格；
- 同目录临时文件、`fsync + os.replace`原子写；
- 不可变历史、活动指针、无正文导入/回滚审计；
- preview/import/eligible/rollback本地CLI；
- 固定模板、七类FAKE样例、运行手册、单元和集成测试。

## 安全不变量

- 未审核、已拒绝、未发布、已撤回、过期、未来、高风险、禁用、无有效来源、
  冲突、禁止回答或转人工知识均不能用于自动回答；
- 正式导入必须重新预览完全相同字节，摘要不匹配或任何error写入0条；
- `operator`只接受`fake-`或`test-`前缀；
- 回滚不删除、不修改历史版本；
- 目录损坏、未知schema或写入失败时不自动重建或覆盖现场；
- 普通CLI和审计不输出或保存知识正文、CSV原始行、绝对路径或真实资料。

## TDD与故障证据

所有生产行为先观察RED，再写最小GREEN。完整逐项证据见
[`logs/phase-07-validation.md`](logs/phase-07-validation.md)。

关键RED覆盖：

- 知识模型、CSV服务、JSON仓库、资格、冲突、回滚和CLI尚不存在；
- 正式导入对未声明运行时可检查的Protocol抛`TypeError`；
- 冲突双方被错误返回；
- 预览缺少批内和活动目录冲突warning；
- 回滚入口和原子失败行为缺失；
- CLI缺少导入/资格/回滚命令；
- 固定CSV资产和可回滚FAKE v2缺失；
- 真实子进程直接执行脚本时无法导入`app`。

所有调试在每个错误两轮限制内完成，没有删除测试、跳过测试、降低断言、关闭
安全检查、忽略异常或用空实现冒充完成。

最终自动化结果：

| 检查 | 结果 |
|---|---|
| 单元测试 | 82项通过 |
| 集成测试 | 12项通过 |
| 契约测试 | 1项通过 |
| 全量测试 | 95项通过 |
| Ruff格式与规则 | 通过 |
| mypy strict | 48个源码文件，0问题 |
| Bandit | 通过 |
| pip-audit | 无已知漏洞 |

## 实际CLI验收

使用Git忽略的`.local/phase07-acceptance-v1.json`和跟踪的FAKE样例：

| 检查 | 结果 |
|---|---|
| preview | 8条、0 error、4 warning |
| 正式导入 | 8条、7个活动ID |
| 回滚前eligible | 4条 |
| 商品活动版本 | v2，明确禁用自动回答 |
| 显式回滚 | `fake-product-001:2->1` |
| 新进程重开eligible | 5条，商品v1恢复资格 |
| 正文或绝对路径输出 | 0 |

第一次嵌套shell封装在进入业务前因多层引号失败，没有创建目录；失败已记录。直接
逐条调用随后发现并修复真实脚本入口问题，最终完整链通过。验收JSON和扫描现场均
保留在Git忽略目录，没有删除。

## 持久化、依赖与迁移

- 运行时schema：本地JSON `schema_version=1`；
- 默认路径：`.local/pdd-knowledge-catalog.json`；
- 第一版写入并发：单Python进程锁；
- 新增数据库表：0；
- 新增TGO Alembic迁移：0；
- 修改TGO数据库：0；
- 新增依赖：0；
- 依赖锁文件变化：0。

本目录不是TGO生产Collection或RAG权限来源。未来正式接入仍必须通过TGO现有
API和权限边界。

## 安全与边界

- `.env`和`.local/`继续被Git忽略；
- `.env.example`只增加空的本地JSON路径变量和安全说明；
- TGO核心`repos/*`修改：0；
- 根Compose和根Makefile修改：0；
- 真实密钥、真实公司资料、真实买家数据和真实业务载荷：0；
- 15个TGO核心容器在实施期间保持`healthy`。

Gitleaks门禁：

- 完整受控源码2021个文件；
- 阶段7候选22项，等于阶段6完整基线22；
- 按规则ID和相对路径归一化后新增0、移除0；
- 候选值未输出。

## 文件摘要

新增：

- 知识领域模型、JSON仓库、治理服务和CLI；
- 模型、CSV、仓库、资格、冲突、回滚、CLI和资产测试；
- 固定CSV模板、七类FAKE样例和可回滚商品v2；
- 知识管理手册、验证日志和本报告。

修改：

- 模型、仓库和服务导出；
- `.gitignore`与`.env.example`本地目录安全项；
- Makefile让统一格式、类型和Bandit命令覆盖`scripts/`；
- 扩展开发手册加入阶段7入口和边界。

`repos/*`、根Compose、根Makefile和依赖锁文件均未修改。

## 明确未实现

- 真实TGO Collection、文档上传、RAG搜索、Embedding或重排；
- 真实模型、拼多多API、店铺授权、Webhook或自动回复；
- 真实商品、物流、售后、公司政策或买家数据导入；
- 阶段8风险路由、完整人工状态机或客服队列；
- 知识管理UI、多进程锁、云存储或生产部署。

## 回滚

不修改当前阶段分支，创建指向阶段6安全状态的新分支：

```bash
git switch -c rollback/phase-07 phase-06-complete
```

检查阶段7安全标签：

```bash
git show --stat phase-07-complete
git diff phase-06-complete..phase-07-complete
```

该回滚不删除JSON、SQLite、Docker卷、数据库、分支或标签。知识版本本身的回滚
使用运行手册中的显式`rollback`命令，只移动活动指针。

## 阶段8门禁

只有以下条件全部满足后才能创建`phase/08-human-handoff-rules`：

1. 全部格式、Ruff、mypy、测试、安全与Gitleaks门禁为PASS；
2. `repos/*`变化为0；
3. 工作区已提交且干净；
4. 本地标签、远程分支、远程标签均指向同一阶段7提交。
