# 阶段8实施计划：确定性风险路由与人工转接

> **执行规范：** 使用`superpowers:executing-plans`串行执行；每个生产行为先按
> `superpowers:test-driven-development`观察预期RED，再写最小GREEN。用户要求
> 本任务不使用子代理。

**目标：** 在阶段5—7本地模拟链上增加可配置、可持久、可审计的确定性风险路由、
人工转接状态机和客服队列，并用现有回复租约阻止AI/人工竞态。

**架构：** `RiskRuleEngine`只做无副作用决策；`HandoffService`编排决策与持久
状态；`SQLiteHandoffRepository`在现有扩展SQLite的同一事务中更新会话模式、
客服队列、审计和阶段6 reply lease。可靠服务取得AI lease和发送前均检查模式。

**技术栈：** Python 3.11标准库`json/unicodedata/sqlite3/asyncio`、Pydantic v2、
FastAPI、pytest、Ruff和mypy；配置为JSON兼容YAML 1.2；新增依赖0。

## 全局约束

- 设计基线：`docs/weekend-run/phase-08-design.md`，提交`110d9eb`。
- 只使用FAKE/TEST标识、消息、操作者、配置和SQLite。
- 不访问真实PDD、TGO业务API、RAG、模型、客服账号、生产或外部网络。
- 不修改`repos/*`、根Compose、根Makefile或依赖锁。
- 不实现阶段9及以后功能。
- 所有故障最多两轮根因分析，保留SQLite、sidecar、日志和未提交diff。
- 每个RED、GREEN、故障和修复写入
  `docs/weekend-run/logs/phase-08-validation.md`。

## 文件结构

预计创建：

```text
config/pdd/transfer_rules.yml
config/pdd/forbidden_claims.yml
extensions/pdd-customer-service/app/models/handoff.py
extensions/pdd-customer-service/app/repositories/handoff.py
extensions/pdd-customer-service/app/repositories/sql/002_handoff.sql
extensions/pdd-customer-service/app/services/risk_routing.py
extensions/pdd-customer-service/app/services/handoff.py
extensions/pdd-customer-service/app/api/handoff.py
extensions/pdd-customer-service/tests/fixtures/handoff.py
extensions/pdd-customer-service/tests/unit/test_risk_routing.py
extensions/pdd-customer-service/tests/unit/test_handoff_repository.py
extensions/pdd-customer-service/tests/unit/test_handoff_service.py
extensions/pdd-customer-service/tests/integration/test_handoff_api.py
docs/runbooks/human-handoff.md
docs/weekend-run/logs/phase-08-validation.md
docs/weekend-run/phase-08-report.md
```

预计修改：

```text
extensions/pdd-customer-service/.env.example
extensions/pdd-customer-service/app/main.py
extensions/pdd-customer-service/app/models/__init__.py
extensions/pdd-customer-service/app/repositories/__init__.py
extensions/pdd-customer-service/app/repositories/reliability.py
extensions/pdd-customer-service/app/services/__init__.py
extensions/pdd-customer-service/docs/runbooks/development.md
extensions/pdd-customer-service/tests/conftest.py
```

---

### 任务1：有类型配置与确定性风险引擎

**文件：**

- 创建：`app/models/handoff.py`
- 创建：`app/services/risk_routing.py`
- 创建：`config/pdd/transfer_rules.yml`
- 创建：`config/pdd/forbidden_claims.yml`
- 创建：`tests/fixtures/handoff.py`
- 创建：`tests/unit/test_risk_routing.py`
- 修改：`app/models/__init__.py`
- 修改：`app/services/__init__.py`

**输出接口：**

```python
class HandoffRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ConversationMode(StrEnum):
    AI = "AI"
    WAITING_HUMAN = "WAITING_HUMAN"
    HUMAN = "HUMAN"
    CLOSED = "CLOSED"

class KnowledgeAvailability(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    CONFLICT = "conflict"
    EXPIRED = "expired"

class RoutingAction(StrEnum):
    CONTINUE_AI = "continue_ai"
    HANDOFF = "handoff"
    BLOCKED = "blocked"

class HandoffReason(StrEnum): ...

class RoutingContext(BaseModel):
    conversation_key: ConversationKey
    message_text: MessageText
    knowledge_status: KnowledgeAvailability
    service_available: bool
    unresolved_count: int
    candidate_reply: MessageText | None

class RoutingDecision(BaseModel):
    action: RoutingAction
    reason: HandoffReason | None
    risk_level: HandoffRiskLevel
    response_text: str | None

class RiskRuleEngine:
    @classmethod
    def from_files(
        cls,
        transfer_rules_path: Path,
        forbidden_claims_path: Path,
    ) -> "RiskRuleEngine": ...
    def evaluate(
        self,
        context: RoutingContext,
        *,
        current_mode: ConversationMode,
    ) -> RoutingDecision: ...
```

- [ ] **步骤1：写配置合同RED**

测试固定JSON兼容YAML文件能加载；缺文件、未知字段、重复优先级、非法原因码、
空关键词和重复claim id均抛脱敏`RiskConfigurationError`，错误不含配置正文或
绝对路径。

运行：

```bash
poetry run python -m pytest \
  tests/unit/test_risk_routing.py::test_rule_configuration_is_strict_and_safe -q
```

预期：模型和引擎尚不存在。

- [ ] **步骤2：实现最小模型、配置解析和规范化**

使用`json.loads`、Pydantic `extra="forbid"`和Unicode NFKC；移除控制字符、
压缩空白、casefold。配置加载不访问网络，不允许空规则降级。

- [ ] **步骤3：写至少50条规则优先级RED**

`tests/fixtures/handoff.py`提供不少于60个独立参数：

| 类别 | 最少用例 |
|---|---:|
| 明确要求人工 | 7 |
| 投诉/举报/法律/监管 | 9 |
| 退款/赔偿/改价 | 9 |
| 改地址/取消/修改订单 | 8 |
| 产品安全/伤害 | 7 |
| 严重质量 | 7 |
| 知识缺失/冲突/过期 | 6 |
| 服务故障/连续两次未解决 | 4 |
| 禁止承诺候选 | 6 |
| 有效知识正常继续 | 5 |

必须包含：

```text
我要退款
我要投诉
帮我改地址
找真人客服
```

每个用例断言动作、原因码和风险；另写组合输入证明优先级选择最先规则。

- [ ] **步骤4：实现规则顺序与禁止承诺**

文本规则由`transfer_rules.yml`提供；知识/服务/次数由有类型字段决定；
`forbidden_claims.yml`只扫描候选回复。`CLOSED`返回blocked，
`WAITING_HUMAN/HUMAN`保持handoff。

- [ ] **步骤5：运行规则GREEN**

```bash
poetry run python -m pytest tests/unit/test_risk_routing.py -q
```

---

### 任务2：SQLite v2迁移、状态机、队列与审计

**文件：**

- 创建：`app/repositories/sql/002_handoff.sql`
- 创建：`app/repositories/handoff.py`
- 创建：`tests/unit/test_handoff_repository.py`
- 修改：`app/repositories/reliability.py`
- 修改：`app/repositories/__init__.py`
- 修改：`app/models/handoff.py`
- 修改：`app/models/__init__.py`

**输出接口：**

```python
class HandoffPersistenceError(RuntimeError): ...
class HandoffTransitionError(ValueError): ...
class HandoffNotFoundError(LookupError): ...

class HandoffRepository(Protocol):
    async def initialize(self) -> None: ...
    async def state(
        self,
        key: ConversationKey,
    ) -> ConversationHandoffState | None: ...
    async def request_handoff(
        self,
        key: ConversationKey,
        *,
        reason: HandoffReason,
        risk_level: HandoffRiskLevel,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState: ...
    async def claim(
        self,
        key: ConversationKey,
        *,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState: ...
    async def resume_ai(
        self,
        key: ConversationKey,
        *,
        operator: str,
        risk_acknowledged: bool,
        occurred_at: datetime,
    ) -> ConversationHandoffState: ...
    async def close(...): ...
    async def queue(self) -> tuple[HandoffQueueItem, ...]: ...
    async def audit_for(
        self,
        key: ConversationKey,
    ) -> tuple[HandoffAuditEvent, ...]: ...

class SQLiteHandoffRepository: ...
```

- [ ] **步骤1：写schema v1到v2迁移RED**

使用真实`001_reliability.sql`创建v1并插入一条FAKE Inbox/Outbox，再初始化阶段8
仓库。断言`user_version=2`、阶段6记录仍存在、新表/索引存在。未知schema失败
且不覆盖。

预期：v2迁移和仓库不存在。

- [ ] **步骤2：实现顺序迁移和严格版本验证**

新库顺序执行001、002；v1只执行002；v2只验证。`002_handoff.sql`不能删除或
重建阶段6表。

- [ ] **步骤3：写状态转换与原子失败RED**

覆盖：

```text
AI -> WAITING_HUMAN -> HUMAN -> AI
AI/WAITING/HUMAN -> CLOSED
WAITING -> AI
HUMAN/WAITING高风险无确认 -> 拒绝
CLOSED -> 任意非CLOSED -> 拒绝
AI -> HUMAN直接领取 -> 拒绝
```

非法转换前后状态、lease、队列和审计完全相同。

- [ ] **步骤4：实现同事务模式、lease、队列和审计**

使用`BEGIN IMMEDIATE`；转人工将owner改为human并递增epoch；恢复AI将mode和
owner/epoch同时更新；开放队列唯一；所有审计无正文。

- [ ] **步骤5：写幂等、队列、重开和脱敏RED**

重复转人工只保留一个开放队列项；领取后状态HUMAN；关闭后队列closed；重建仓库
状态保持。损坏/不可写数据库抛固定异常，不含路径、SQL、文本。

- [ ] **步骤6：运行仓库GREEN**

```bash
poetry run python -m pytest \
  tests/unit/test_handoff_repository.py \
  tests/unit/test_reliability_store.py -q
```

---

### 任务3：转接服务与AI/人工竞态

**文件：**

- 创建：`app/services/handoff.py`
- 创建：`tests/unit/test_handoff_service.py`
- 修改：`app/services/__init__.py`
- 修改：`app/repositories/reliability.py`
- 修改：`tests/unit/test_reliable_service.py`

**输出接口：**

```python
class HandoffUnavailableError(RuntimeError): ...

class HandoffService:
    async def evaluate_and_route(
        self,
        context: RoutingContext,
    ) -> RoutingDecision: ...
    async def state(...): ...
    async def queue(...): ...
    async def claim(...): ...
    async def resume_ai(...): ...
    async def close(...): ...
```

- [ ] **步骤1：写规则决策到持久转接RED**

`我要退款`产生固定转接提示、WAITING_HUMAN、human lease、单一queue和无正文
审计；有效知识正常问题保持AI且不写queue。

- [ ] **步骤2：实现服务编排和脱敏故障**

服务先读取模式，再运行引擎；handoff调用单个原子仓库方法；仓库故障转换为固定
`HandoffUnavailableError`，不回显路径、SQL、买家文本或候选回复。

- [ ] **步骤3：写人工接管和新消息阻断RED**

完成WAITING→HUMAN后提交新合成消息，断言Adapter发送0、结果failed、
reason为human/mode阻断。

- [ ] **步骤4：写AI发送前竞态RED**

使用阻塞Adapter让AI取得旧epoch；在发送前调用转人工；释放阻塞后断言AI发送0、
旧任务failed、queue一项、审计有handoff和`ai_reply_blocked`。

- [ ] **步骤5：写恢复与重启RED**

WAITING/HUMAN显式恢复后新epoch可发送；high无确认拒绝；确认后可发送；
CLOSED永远不能发送；旧Outbox重启恢复遇到非AI模式不发送。

- [ ] **步骤6：修改可靠租约检查并运行GREEN**

`acquire_ai_lease`和`lease_is_current`要求模式缺失或AI。运行：

```bash
poetry run python -m pytest \
  tests/unit/test_handoff_service.py \
  tests/unit/test_reliable_service.py -q
```

---

### 任务4：本地客服队列API

**文件：**

- 创建：`app/api/handoff.py`
- 创建：`tests/integration/test_handoff_api.py`
- 修改：`app/main.py`
- 修改：`tests/conftest.py`
- 修改：`.env.example`

- [ ] **步骤1：写evaluate与queue RED**

POST四个验收短语分别返回handoff、固定提示和原因码；GET queue只返回模式、
FAKE会话键、风险、原因、时间，不回显消息文本。

- [ ] **步骤2：实现依赖注入和启动初始化**

`create_app`接受注入的handoff repository/engine；默认与可靠store共用同一
SQLite路径；lifespan顺序初始化可靠schema v2、handoff仓库、恢复Outbox。

- [ ] **步骤3：写claim/resume/close RED**

覆盖WAITING→HUMAN、显式恢复、高风险确认、CLOSED终态、未知会话404、
非法转换409和数据库故障脱敏503。

- [ ] **步骤4：实现状态API并运行GREEN**

```bash
poetry run python -m pytest tests/integration/test_handoff_api.py -q
```

- [ ] **步骤5：完整阶段5—7回归**

```bash
poetry run python -m pytest \
  tests/integration \
  tests/contract \
  tests/unit/test_knowledge_service.py \
  tests/unit/test_reliable_service.py -q
```

---

### 任务5：运行手册、最终门禁、提交和发布

**文件：**

- 创建：`docs/runbooks/human-handoff.md`
- 创建：`docs/weekend-run/logs/phase-08-validation.md`
- 创建：`docs/weekend-run/phase-08-report.md`
- 修改：`extensions/pdd-customer-service/docs/runbooks/development.md`

- [ ] **步骤1：编写人工转接运行手册**

包括规则顺序、配置合同、固定提示、模式图、合法/非法转换、队列接口、高风险
恢复、schema v2备份/恢复、无删除故障处理和FAKE/TEST边界。

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
git diff --name-only phase-07-complete -- repos
git status --short -- repos
git check-ignore -v .local/pdd-reliability.sqlite3
```

Gitleaks完整受控源码不得超过22项阶段7基线，阶段8新增必须为0；候选值不输出。
新增依赖0、锁文件变化0、TGO核心变化0、真实资料0。15个TGO容器继续healthy。

- [ ] **步骤4：实际进程验收**

使用Git忽略的新SQLite和真实Uvicorn本地进程：

1. 健康检查；
2. POST`我要退款`进入WAITING和queue；
3. WAITING下新消息AI发送被阻止；
4. claim后HUMAN；
5. 显式resume后AI测试固定回复恢复；
6. high无确认无法恢复；
7. close后永久阻止；
8. 重启后状态、queue和审计保持。

不创建真实客服或浏览器账号。

- [ ] **步骤5：创建阶段报告**

记录设计/计划提交、50+规则、状态机、迁移、竞态、API、测试数量、实际进程、
Docker、依赖、核心边界、Gitleaks、失败和回滚。

- [ ] **步骤6：最终提交、标签和推送**

提交：

```text
feat: add deterministic risk routing and human handoff
```

标签：

```text
phase-08-complete
```

确认本地和远程无同名引用后推送阶段分支和标签到`origin`。禁止强推、PR和主分支
合并。本地HEAD、标签、远程分支和远程标签必须一致。

- [ ] **步骤7：停止实施门禁**

阶段8全部PASS后不再实现阶段9功能，只创建：

```text
docs/weekend-run/phase-09-to-18-readiness.md
docs/weekend-run/final-report.md
docs/weekend-run/status.json
```
