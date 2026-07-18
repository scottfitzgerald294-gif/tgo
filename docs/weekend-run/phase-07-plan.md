# 阶段7实施计划：知识数据框架

> **执行规范：** 使用`superpowers:executing-plans`串行执行；每个生产行为先按
> `superpowers:test-driven-development`观察预期RED，再写最小GREEN。用户要求
> 本任务不使用子代理。

**目标：** 建立只使用FAKE/TEST数据的七类知识模型、CSV预览/正式导入、JSON持久
目录、活动版本、冲突检测、自动回答资格和无删除回滚。

**架构：** `KnowledgeCatalogService`负责CSV和确定性治理；`JsonKnowledgeRepository`
负责扩展自有本地JSON快照；CLI只调用服务，不复制规则。目录文件不是TGO生产知识
库，阶段7不调用RAG、模型、PDD或TGO API。

**技术栈：** Python 3.11标准库`csv/json/hashlib/os/threading/argparse`、
Pydantic v2、pytest、Ruff和mypy；新增依赖0。

## 全局约束

- 设计基线：`docs/weekend-run/phase-07-design.md`，提交`411687c`。
- 只使用明显标注的`FAKE/TEST`记录、来源和operator。
- 不访问真实公司资料、真实PDD、TGO业务API、模型、RAG或外部网络。
- 不修改`repos/*`、根Compose、根Makefile或依赖锁文件。
- 不实现阶段8风险状态机或人工队列。
- 运行时JSON、临时文件和失败现场不进入Git、不自动删除。
- 每个RED、GREEN、故障和修复写入
  `docs/weekend-run/logs/phase-07-validation.md`。

## 文件结构

预计创建：

```text
extensions/pdd-customer-service/app/models/knowledge.py
extensions/pdd-customer-service/app/repositories/knowledge.py
extensions/pdd-customer-service/app/services/knowledge.py
extensions/pdd-customer-service/scripts/knowledge_catalog.py
extensions/pdd-customer-service/tests/fixtures/knowledge.py
extensions/pdd-customer-service/tests/unit/test_knowledge_models.py
extensions/pdd-customer-service/tests/unit/test_knowledge_csv.py
extensions/pdd-customer-service/tests/unit/test_knowledge_repository.py
extensions/pdd-customer-service/tests/unit/test_knowledge_service.py
extensions/pdd-customer-service/tests/integration/test_knowledge_cli.py
knowledge/pdd/knowledge-import-template.csv
knowledge/pdd/fake-knowledge.csv
docs/runbooks/knowledge-management.md
docs/weekend-run/logs/phase-07-validation.md
docs/weekend-run/phase-07-report.md
```

预计修改：

```text
.gitignore
extensions/pdd-customer-service/.env.example
extensions/pdd-customer-service/app/models/__init__.py
extensions/pdd-customer-service/app/repositories/__init__.py
extensions/pdd-customer-service/app/services/__init__.py
extensions/pdd-customer-service/docs/runbooks/development.md
```

---

### 任务1：知识模型与静态安全资格

**文件：**

- 创建：`app/models/knowledge.py`
- 创建：`tests/unit/test_knowledge_models.py`
- 修改：`app/models/__init__.py`

**输出接口：**

```python
class KnowledgeKind(StrEnum):
    PRODUCT = "product"
    SKU = "sku"
    FAQ = "faq"
    SHIPPING = "shipping"
    AFTER_SALES = "after_sales"
    FORBIDDEN_ANSWER = "forbidden_answer"
    HANDOFF_CONDITION = "handoff_condition"

class KnowledgeStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"

class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class KnowledgeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    knowledge_id: Identifier
    version: int
    kind: KnowledgeKind
    title: str
    content: str
    status: KnowledgeStatus
    approval_status: ApprovalStatus
    applicable_shop: Identifier
    applicable_product: Identifier
    applicable_sku: Identifier
    source: str
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    risk_level: RiskLevel
    allowed_for_auto_reply: bool
    reviewed_by: Identifier | None
```

模型还包括`KnowledgeIssue`、`ImportPreview`、`KnowledgeActiveVersion`、
`KnowledgeAuditEvent`、`KnowledgeCatalog`、`KnowledgeScope`、
`KnowledgeImportResult`和`KnowledgeRollbackResult`。

- [ ] **步骤1：写七类和全部字段RED**

参数化七种`kind`构造记录，断言枚举值稳定，模型字段集合包含用户要求的13个
治理字段及`kind/title/content`。

运行：

```bash
poetry run python -m pytest \
  tests/unit/test_knowledge_models.py::test_all_seven_knowledge_kinds_have_required_governance_fields -q
```

预期：无法导入`KnowledgeKind`和`KnowledgeRecord`。

- [ ] **步骤2：实现最小枚举、约束和目录模型**

标识1至128字符、标题1至200、正文1至8000、version大于0、时间带时区且
`expires_at > effective_at`。`approved`必须有reviewer；其他状态允许
`reviewed_by=None`。

- [ ] **步骤3：写非法时间和审核RED并实现**

验证无时区、倒置时间、approved无reviewer均抛`ValidationError`。

- [ ] **步骤4：运行模型GREEN**

```bash
poetry run python -m pytest tests/unit/test_knowledge_models.py -q
```

---

### 任务2：CSV合同、摘要与只读预览

**文件：**

- 创建：`app/services/knowledge.py`
- 创建：`tests/fixtures/knowledge.py`
- 创建：`tests/unit/test_knowledge_csv.py`
- 修改：`app/services/__init__.py`

**输出接口：**

```python
KNOWLEDGE_CSV_HEADERS: tuple[str, ...]

class KnowledgeCatalogService:
    async def preview_csv(
        self,
        csv_text: str,
        *,
        now: datetime,
    ) -> ImportPreview: ...
```

- [ ] **步骤1：写缺表头和缺字段RED**

空CSV、缺任一固定表头、数据行列数不匹配分别返回`missing_header`或
`row_validation_error`，preview写入数为0。

预期：服务尚不存在。

- [ ] **步骤2：实现严格UTF-8文本CSV解析**

使用`csv.DictReader`，表头必须与固定集合完全一致；空字符串不获得业务默认值；
布尔只接受小写`true/false`；时间使用Pydantic aware datetime解析。

- [ ] **步骤3：写SHA-256稳定性和预览零写入RED**

相同字节得到相同64位小写digest；任何空格或换行变化产生不同digest；调用预览
前后仓库快照完全相同。

- [ ] **步骤4：写来源、重复和安全warning RED**

覆盖：

- 空或非`FAKE://`/`TEST://`来源：`invalid_source` error；
- 批内相同`knowledge_id + version`：`duplicate_in_batch` error；
- draft/pending/expired/future/high/auto-disabled：对应warning；
- warning不增加`error_count`。

- [ ] **步骤5：实现问题分类并运行CSV GREEN**

```bash
poetry run python -m pytest tests/unit/test_knowledge_csv.py -q
```

---

### 任务3：原子JSON目录、正式导入和重开

**文件：**

- 创建：`app/repositories/knowledge.py`
- 创建：`tests/unit/test_knowledge_repository.py`
- 修改：`app/repositories/__init__.py`
- 修改：`.gitignore`
- 修改：`.env.example`

**输出接口：**

```python
class KnowledgePersistenceError(RuntimeError): ...
class DuplicateKnowledgeVersionError(ValueError): ...
class KnowledgeVersionNotFoundError(LookupError): ...
class KnowledgeVersionAlreadyActiveError(ValueError): ...

class KnowledgeRepository(Protocol):
    async def initialize(self) -> None: ...
    async def snapshot(self) -> KnowledgeCatalog: ...
    async def import_records(...) -> KnowledgeImportResult: ...
    async def rollback(...) -> KnowledgeRollbackResult: ...

class JsonKnowledgeRepository:
    def __init__(self, catalog_path: Path) -> None: ...
```

- [ ] **步骤1：写初始化和导入重开RED**

构造函数不得创建文件。`initialize()`创建schema v1空目录；导入两版同ID后重建
仓库对象，记录仍为2条且活动版本为最高版本。

预期：仓库尚不存在。

- [ ] **步骤2：实现单进程锁和原子写**

公共异步方法使用`asyncio.to_thread`，同步临界区使用`threading.Lock`。序列化
使用`model_dump(mode="json")`，临时文件与目标同目录，`flush + fsync`后
`os.replace`。错误转换为不含绝对路径/正文的`KnowledgePersistenceError`。

- [ ] **步骤3：写目录重复和批次原子RED**

目录已有相同`knowledge_id + version`时整个批次写入0条；异常前后文件内容和
活动指针相同。

- [ ] **步骤4：写损坏JSON、未知schema和写失败RED**

三种情况均抛脱敏异常，异常文本不含绝对路径或知识正文，不自动重建或覆盖现场。

- [ ] **步骤5：运行仓库GREEN**

```bash
poetry run python -m pytest tests/unit/test_knowledge_repository.py -q
```

并确认：

```bash
git check-ignore -v \
  extensions/pdd-customer-service/.local/pdd-knowledge-catalog.json
```

---

### 任务4：正式导入、冲突、资格和回滚

**文件：**

- 修改：`app/services/knowledge.py`
- 创建：`tests/unit/test_knowledge_service.py`

**输出接口：**

```python
class PreviewDigestMismatchError(ValueError): ...
class KnowledgeImportBlockedError(ValueError): ...

class KnowledgeCatalogService:
    async def import_csv(
        self,
        csv_text: str,
        *,
        expected_digest: str,
        operator: str,
        now: datetime,
    ) -> KnowledgeImportResult: ...
    async def eligible_records(
        self,
        scope: KnowledgeScope,
        *,
        now: datetime,
    ) -> tuple[KnowledgeRecord, ...]: ...
    async def rollback(
        self,
        knowledge_id: str,
        *,
        to_version: int,
        operator: str,
        now: datetime,
    ) -> KnowledgeRollbackResult: ...
```

- [ ] **步骤1：写摘要不匹配与error阻止导入RED**

两种情况均断言仓库记录0、活动版本0、审计0。

- [ ] **步骤2：实现重新预览后原子正式导入**

operator只接受`fake-`或`test-`前缀。warning允许保存，error阻止。批次同ID多版
按version升序保存并把最高版本设为活动版本。

- [ ] **步骤3：写资格矩阵RED**

参数化证明以下记录均不返回：

- draft或withdrawn；
- pending或rejected；
- 无有效来源；
- future或expired；
- high；
- `allowed_for_auto_reply=false`；
- forbidden/handoff类别。

唯一正例为当前作用域内、published、approved、有reviewer、有效期内、低/中风险
且允许自动回答的活动版本。

- [ ] **步骤4：实现活动版本和作用域筛选**

作用域每层相等或知识层为`*`才匹配查询。只使用活动版本。

- [ ] **步骤5：写冲突矩阵RED**

至少覆盖：

- 同kind、不同content、作用域和时间重叠：双方不合格；
- 内容相同：不冲突；
- kind不同：不冲突；
- shop/product/sku完全分离：不冲突；
- 时间不重叠：不冲突；
- 非published或非approved：不参与冲突。

- [ ] **步骤6：实现确定性冲突检测**

正文用`" ".join(content.split()).casefold()`规范化；时间用半开区间
`[effective_at, expires_at)`；冲突涉及的活动记录全部排除。

- [ ] **步骤7：写回滚RED并实现**

导入v1、v2后回滚到v1，断言：

- 历史记录仍2条；
- 活动版本变为1；
- 资格返回v1；
- 审计记录from=2、to=1、operator；
- 不存在版本和回滚到当前版本均零修改。

- [ ] **步骤8：运行服务GREEN和阶段6回归**

```bash
poetry run python -m pytest \
  tests/unit/test_knowledge_service.py \
  tests/unit/test_reliable_service.py -q
```

---

### 任务5：CLI、模板和七类虚构示例

**文件：**

- 创建：`scripts/knowledge_catalog.py`
- 创建：`tests/integration/test_knowledge_cli.py`
- 创建：`knowledge/pdd/knowledge-import-template.csv`
- 创建：`knowledge/pdd/fake-knowledge.csv`

- [ ] **步骤1：写CLI预览RED**

调用`main(["--catalog", tmp_json, "preview", "--csv", fake_csv])`，断言退出0，
输出只含digest、counts、issue codes和ID，不含content。

预期：脚本尚不存在。

- [ ] **步骤2：实现preview和import命令**

所有命令显式初始化仓库。`import`必须提供预览digest和FAKE/TEST operator；
摘要错误退出2且写入0条。

- [ ] **步骤3：写eligible与rollback RED并实现**

导入后eligible只输出合格记录ID/version；rollback后活动版本变化。CLI输出不得
含知识正文、绝对catalog路径或CSV原始行。

- [ ] **步骤4：创建固定模板和示例**

模板只有固定16列表头。示例包含七类，每条：

- ID或内容明显带FAKE/TEST；
- source为`FAKE://`或`TEST://`；
- 不含真实品牌、店铺、订单、地址、电话或账号；
- 时间使用带`Z`的固定合成值；
- forbidden/handoff的`allowed_for_auto_reply=false`。

- [ ] **步骤5：运行CLI GREEN**

```bash
poetry run python -m pytest tests/integration/test_knowledge_cli.py -q
```

并实际使用临时忽略目录执行preview、import、eligible、rollback、重开查询。

---

### 任务6：运行手册、最终门禁、提交和发布

**文件：**

- 创建：`docs/runbooks/knowledge-management.md`
- 创建：`docs/weekend-run/logs/phase-07-validation.md`
- 创建：`docs/weekend-run/phase-07-report.md`
- 修改：`extensions/pdd-customer-service/docs/runbooks/development.md`

- [ ] **步骤1：编写知识管理手册**

包括CSV合同、preview/import分离、问题码、资格条件、冲突规则、回滚、不删除
恢复、默认路径、单进程限制和FAKE/TEST边界。

- [ ] **步骤2：运行完整质量命令**

```bash
make format
make lint
make test-unit
make test-integration
make test
make security-check
```

- [ ] **步骤3：安全与边界门禁**

```bash
git diff --check
git diff --name-only phase-06-complete -- repos
git status --short -- repos
git check-ignore -v .local/pdd-knowledge-catalog.json
```

Gitleaks完整受控源码不得超过22项既有基线，阶段7新增必须为0；候选值不输出。
新增依赖0、锁文件变化0、TGO核心变化0、真实资料0。

- [ ] **步骤4：创建阶段报告**

记录RED/GREEN、七类数据、预览零写入、正式导入、资格矩阵、冲突、回滚、重开、
测试数量、Docker、依赖、核心边界和Gitleaks。

- [ ] **步骤5：最终提交、标签和推送**

提交：

```text
feat: add versioned and reviewable knowledge framework
```

标签：

```text
phase-07-complete
```

确认本地和远程无同名引用后推送阶段分支和标签到`origin`。禁止强推、PR和主分支
合并。本地HEAD、标签、远程分支和远程标签必须一致。

- [ ] **步骤6：进入阶段8门禁**

只有阶段7全部PASS、远程引用一致且工作区干净，才从`phase-07-complete`创建
`phase/08-human-handoff-rules`。
