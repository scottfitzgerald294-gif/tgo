# 本地知识目录管理手册

## 适用范围

本手册只适用于`extensions/pdd-customer-service/`阶段7的本地、单进程、
`FAKE/TEST`知识目录。它用于验证知识审核、版本、冲突、资格和回滚，不是TGO
生产知识库，也不调用TGO RAG、模型、拼多多接口、外部网络或真实公司资料。

默认目录文件：

```text
extensions/pdd-customer-service/.local/pdd-knowledge-catalog.json
```

该文件由根`.gitignore`中的`.local/`规则忽略。构造仓库对象不会创建文件；CLI
显式初始化时才创建schema v1空目录。第一版只有进程内锁，禁止多个进程同时写同
一个目录文件，也不得直接用于生产、多副本或网络文件系统。

## CSV合同与合成数据

模板：

```text
knowledge/pdd/knowledge-import-template.csv
```

七类虚构示例：

```text
knowledge/pdd/fake-knowledge.csv
```

固定UTF-8表头顺序：

```text
knowledge_id,version,kind,title,content,status,approval_status,
applicable_shop,applicable_product,applicable_sku,source,effective_at,
expires_at,risk_level,allowed_for_auto_reply,reviewed_by
```

规则：

- `kind`只允许`product`、`sku`、`faq`、`shipping`、`after_sales`、
  `forbidden_answer`、`handoff_condition`；
- `version`必须为大于0的整数；
- 布尔值只允许小写`true`或`false`；
- 时间必须带时区，且`expires_at`晚于`effective_at`；
- `approved`必须有合成审核者；
- `source`只允许`FAKE://`或`TEST://`；
- 标识、标题和正文必须明显为虚构测试数据；
- 空字段不会获得隐藏业务默认值。

不得将真实商品、店铺、订单、物流、售后政策、买家资料、账号、地址、电话、密钥
或公司文档放入CSV、目录、日志或截图。

## 预览与正式导入

从扩展目录执行：

```bash
cd extensions/pdd-customer-service
poetry run python scripts/knowledge_catalog.py \
  --catalog .local/pdd-knowledge-catalog.json \
  preview \
  --csv ../../knowledge/pdd/fake-knowledge.csv
```

预览输出只包含SHA-256摘要、记录数、错误/警告数、问题码、知识ID和版本，不输出
正文、CSV原始行或绝对目录路径。预览不会写入记录、活动指针或审计。

人工核对预览后，把该次输出的64位`digest`原样用于正式导入：

```bash
poetry run python scripts/knowledge_catalog.py \
  --catalog .local/pdd-knowledge-catalog.json \
  import \
  --csv ../../knowledge/pdd/fake-knowledge.csv \
  --expected-digest '复制刚刚审核通过的64位digest' \
  --operator test-local-reviewer
```

CLI会重新读取和预览文件。任何字节变化都会导致摘要不匹配并写入0条；存在
`error`也写入0条。`warning`允许保存，但相应知识仍会被资格规则排除。

## 问题码

| 级别 | 问题码 | 行为 |
|---|---|---|
| error | `missing_header` | 表头不完全匹配，禁止导入 |
| error | `row_validation_error` | 行字段、类型、时间或治理约束无效，禁止导入 |
| error | `duplicate_in_batch` | 同批`knowledge_id + version`重复，禁止导入 |
| error | `duplicate_in_catalog` | 不可变版本已存在，禁止导入 |
| error | `invalid_source` | 来源不是`FAKE://`或`TEST://`，禁止导入 |
| warning | `not_published` | 非published，不可自动回答 |
| warning | `unreviewed` | 未批准或无审核者，不可自动回答 |
| warning | `expired` | 已过期，不可自动回答 |
| warning | `not_yet_effective` | 尚未生效，不可自动回答 |
| warning | `high_risk` | 高风险，不可自动回答 |
| warning | `auto_reply_disabled` | 明确禁用，不可自动回答 |
| warning | `knowledge_conflict` | 活动候选冲突，冲突双方不可自动回答 |

## 自动回答资格

查询某一合成作用域：

```bash
poetry run python scripts/knowledge_catalog.py \
  --catalog .local/pdd-knowledge-catalog.json \
  eligible \
  --shop fake-shop \
  --product fake-product-001 \
  --sku fake-sku-blue
```

只返回每个`knowledge_id`的活动版本，并同时要求：

1. `published + approved`且有审核者；
2. 来源合法，当前时间位于半开生效区间；
3. 非高风险且`allowed_for_auto_reply=true`；
4. 类别不是`forbidden_answer`或`handoff_condition`；
5. 店铺、商品、SKU逐层精确匹配或知识侧为`*`；
6. 当前活动集合中不存在冲突。

目录读取、schema或持久化失败时不会返回可自动回答知识。

## 冲突规则

两条活动知识只有同时满足以下全部条件才冲突：

1. 类别相同；
2. 去除多余空白并忽略大小写后的正文不同；
3. 店铺、商品、SKU三层作用域均重叠，相等或任一侧为`*`视为重叠；
4. 生效时间半开区间重叠；
5. 双方均为`published + approved`。

内容相同、类别不同、任一作用域完全分离、时间不重叠、未发布或未批准都不构成
冲突。冲突只影响自动回答资格，不删除不可变历史记录。

## 回滚与恢复

把一个知识ID的活动指针从当前版本显式切换到已存在版本：

```bash
poetry run python scripts/knowledge_catalog.py \
  --catalog .local/pdd-knowledge-catalog.json \
  rollback \
  --knowledge-id fake-knowledge-001 \
  --to-version 1 \
  --operator test-local-operator
```

回滚不会修改或删除任何历史版本，只更新活动指针并追加
`knowledge_rolled_back`审计。审计只有事件ID、事件类型、知识ID、起止版本、合成
操作者和时间，不含标题、正文或来源。

目标不存在或已经是活动版本时，活动指针和审计均保持不变。故障时保留JSON和
临时文件现场，不自动重建、覆盖、删除或“修复”。需要恢复时：

1. 停止所有写入该目录的本地进程；
2. 只读复制当前JSON和同目录临时文件到Git忽略的备份位置；
3. 记录固定错误码和操作，不复制正文到共享报告；
4. 由人工确认文件来源和目标版本后再使用显式回滚。

禁止删除JSON、数据库、Docker卷、分支或标签来处理知识问题。

## 安全检查

```bash
git check-ignore -v \
  extensions/pdd-customer-service/.local/pdd-knowledge-catalog.json
make lint
make test
make security-check
```

如果出现真实资料、真实凭据、未知schema、重复版本、摘要不匹配、冲突或扫描失败，
立即停止正式导入，保留现场并记录结果；不得降低校验、跳过测试或关闭扫描。
