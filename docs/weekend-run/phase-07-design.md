# 阶段7设计：可审核、版本化的本地知识目录

## 批准依据

用户在无人值守执行附件中明确授权自动执行到阶段8，并为阶段7指定七类知识、
统一元数据、CSV模板、JSON或数据库模型、虚构示例、校验、预览、正式导入、
冲突检测、版本回滚和自动回答安全条件。

本设计只实现这些本地治理能力，不接入真实TGO RAG、真实模型、真实PDD、生产
知识库或公司资料。附件要求无人值守连续执行，因此其中的明确范围和验收标准
作为本阶段设计预批准依据。

## 目标与不变量

目标是建立一个可持久、可预览、可审核、可回滚的本地知识目录，为阶段8确定性
规则提供合成知识状态，但不执行RAG检索或生成回答。

安全不变量：

1. 只有活动版本可以参与资格判断。
2. 未审核、过期、无来源、冲突、高风险或明确禁用的知识不能用于自动回答。
3. 正式导入前必须对完全相同的CSV内容生成预览摘要。
4. 已导入版本不可修改；回滚只改变活动版本指针并追加审计。
5. 阶段7只接受`FAKE://`或`TEST://`来源和明显虚构内容。
6. 普通日志和审计不保存知识正文。
7. 目录故障时不返回可自动回答知识。

## 方案比较

### 方案A：扩展自有JSON快照目录

使用Pydantic模型和Python标准库`json/csv/hashlib/os`。目录文件保存不可变记录、
活动版本指针和不含正文的审计事件；写入先生成同目录临时文件，再用
`os.replace`原子替换。优点是零新增依赖、数据结构直接可审阅、适合小规模本地
框架、无需TGO或数据库迁移。限制是第一版只支持单进程写入，不提供多进程锁或
生产级事务。

### 方案B：扩展自有SQLite知识账本

可以获得唯一约束和事务，但会增加第二套schema、迁移和约800行持久层代码，
阶段7的小规模合成目录不需要该复杂度，也更容易被误解为平行生产知识库，因此
不选。

### 方案C：直接把CSV作为运行时知识源

最容易查看，但不能可靠分离预览和正式导入，活动版本、回滚、审计和冲突状态难以
原子维护；CSV编辑也可能绕过验证，因此不选。

选择方案A。

## 边界与目录

运行代码只放在：

```text
extensions/pdd-customer-service/
  app/models/knowledge.py
  app/repositories/knowledge.py
  app/services/knowledge.py
  scripts/knowledge_catalog.py
```

跟踪的模板和虚构示例放在：

```text
knowledge/pdd/knowledge-import-template.csv
knowledge/pdd/fake-knowledge.csv
```

默认运行时目录文件：

```text
extensions/pdd-customer-service/.local/pdd-knowledge-catalog.json
```

根`.gitignore`增加安全规则`.local/`。模板和示例继续被跟踪，运行时目录、临时
文件和本地目录状态不得进入Git。

本阶段不修改`repos/*`，不调用TGO API，也不把本地目录当成TGO Project、
Collection或Agent权限来源。未来正式接入时，TGO仍是生产知识权限和RAG服务的
系统边界。

## 领域模型

### 知识类别

`KnowledgeKind`固定为：

```text
product
sku
faq
shipping
after_sales
forbidden_answer
handoff_condition
```

第一版使用统一文本结构，而不是为七类数据发明未经需求验证的外部字段：

- `title`：可审核标题；
- `content`：静态合成知识正文；
- `kind`：七类之一；
- `applicable_shop/product/sku`：作用域，`*`表示该层通配；
- 统一治理元数据。

### 必需元数据

每条`KnowledgeRecord`都有：

```text
knowledge_id
version
status
approval_status
applicable_shop
applicable_product
applicable_sku
source
effective_at
expires_at
risk_level
allowed_for_auto_reply
reviewed_by
```

附加必需字段：

```text
kind
title
content
```

枚举：

- `status`：`draft / published / withdrawn`
- `approval_status`：`pending / approved / rejected`
- `risk_level`：`low / medium / high`

约束：

- `knowledge_id`和作用域标识为1至128字符；
- `version`为大于0的整数；
- 标题1至200字符，正文1至8000字符；
- `effective_at`、`expires_at`必须带时区，且结束时间晚于开始时间；
- `source`必须为非空`FAKE://`或`TEST://`引用；
- `reviewed_by`字段必须存在；`approved`时必须是非空的合成审核者标识，
  `pending/rejected`允许空值；
- `high`风险永远不能用于自动回答；
- `forbidden_answer`和`handoff_condition`永远不能作为自动回答正文。

## JSON目录格式

`KnowledgeCatalog`包含：

```text
schema_version = 1
records: 不可变KnowledgeRecord列表
active_versions: KnowledgeActiveVersion列表
audit_events: KnowledgeAuditEvent列表
```

唯一键是`knowledge_id + version`。活动版本按`knowledge_id`唯一。审计只保存：

```text
event_id
event
knowledge_id
from_version
to_version
operator
occurred_at
```

审计不保存`title`、`content`、`source`或完整CSV行。

仓库构造函数不读取或创建文件。`initialize()`在CLI或测试显式调用；文件不存在
时创建空schema v1目录，文件损坏、schema未知或原子写失败时抛出脱敏
`KnowledgePersistenceError`。

## CSV合同

CSV固定UTF-8，表头顺序为：

```text
knowledge_id,version,kind,title,content,status,approval_status,
applicable_shop,applicable_product,applicable_sku,source,effective_at,
expires_at,risk_level,allowed_for_auto_reply,reviewed_by
```

布尔值只接受`true/false`。空字段不被偷偷填默认值。模板仅有表头；示例文件包含
七类明显虚构记录，所有标识带`fake-`或`test-`，来源为`FAKE://`或`TEST://`。

## 预览、正式导入与问题分类

`KnowledgeCatalogService.preview_csv(csv_text, now)`执行：

1. 计算原始UTF-8字节的SHA-256摘要；
2. 校验完整表头；
3. 解析每行并生成Pydantic模型；
4. 检测批内和目录内重复`knowledge_id + version`；
5. 检测来源、时间、审核、风险和冲突；
6. 返回`ImportPreview`，不写文件。

问题结构：

```text
code
severity
row_number
knowledge_id
message
```

阻断正式导入的`error`：

- `missing_header`
- `row_validation_error`
- `duplicate_in_batch`
- `duplicate_in_catalog`
- `invalid_source`

允许保存但阻止自动回答的`warning`：

- `not_published`
- `unreviewed`
- `expired`
- `not_yet_effective`
- `high_risk`
- `auto_reply_disabled`
- `knowledge_conflict`

`import_csv(csv_text, expected_digest, operator, now)`重新生成预览，并要求：

- 当前摘要严格等于`expected_digest`；
- 没有`error`；
- `operator`为合成的非空标识。

通过后一次性原子保存全部新版本、更新每个`knowledge_id`的活动版本为导入版本，
并为每个活动指针变化追加不含正文的`knowledge_imported`审计。摘要不匹配或存在
阻断问题时写入0条。

## 冲突检测

两条知识只有同时满足以下条件才冲突：

1. `kind`相同；
2. `content`规范化后不同；
3. 店铺、商品和SKU三个作用域逐层重叠；相等或任一方为`*`视为重叠；
4. 生效时间窗口重叠；
5. 均为`published + approved`。

冲突按活动版本计算。冲突涉及的所有记录都不能自动回答。不同类别、作用域完全
分离、时间不重叠或内容相同不构成冲突。

## 自动回答资格

`eligible_records(scope, now)`只返回活动版本，并逐条要求：

- `status=published`
- `approval_status=approved`
- `source`有效
- 已到`effective_at`
- 未到`expires_at`
- `risk_level`不是`high`
- `allowed_for_auto_reply=true`
- `kind`不是`forbidden_answer/handoff_condition`
- 当前活动集合中无冲突

任一条件失败就不返回该记录。方法只提供确定性本地资格筛选，不调用RAG、不生成
回答、不发送消息。

## 回滚

`rollback(knowledge_id, to_version, operator, now)`：

1. 要求目标版本已存在且属于相同`knowledge_id`；
2. 要求目标不是当前活动版本；
3. 原子更新活动版本指针；
4. 追加`knowledge_rolled_back`审计，记录from/to版本和operator；
5. 不修改或删除任何历史记录。

回滚后的自动回答资格重新按目标版本和全局冲突计算。不存在目标、相同版本回滚或
持久故障时，活动指针和审计均不改变。

## CLI

`scripts/knowledge_catalog.py`提供：

```text
preview --csv <path>
import --csv <path> --expected-digest <sha256> --operator <TEST标识>
eligible --shop <id> --product <id> --sku <id>
rollback --knowledge-id <id> --to-version <n> --operator <TEST标识>
```

CLI默认只输出摘要、计数、问题码、knowledge_id和版本，不输出知识正文。正式导入
和回滚必须显式提供operator。CLI不访问网络。

## 测试策略

测试只使用`tmp_path`和`FAKE/TEST`数据：

- 七类知识和全部字段模型；
- 缺表头、缺字段、错误布尔值、无时区和非法来源；
- 批内重复、目录重复和持久重开；
- 未审核、过期、未来、禁用、高风险不能自动回答；
- 冲突和非冲突作用域/时间组合；
- 预览零写入、摘要不匹配零写入、正式导入原子写；
- 活动版本和回滚审计；
- 损坏JSON、未知schema和写入失败安全处理；
- CLI预览、导入、资格查询和回滚；
- 阶段6的44项回归继续通过。

## 明确不做

- 不接入真实TGO Collection、文档上传或RAG搜索；
- 不接入真实模型、Embedding或重排；
- 不导入真实商品、物流、售后或公司政策；
- 不实现阶段8风险路由和人工状态机；
- 不创建知识管理UI；
- 不修改TGO核心、根Compose或依赖锁；
- 不提供多进程写锁、云存储或生产部署。
