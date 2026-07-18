# 阶段6实施计划：消息可靠性机制

> **执行规范：** 使用`superpowers:executing-plans`串行执行；每个生产行为先按
> `superpowers:test-driven-development`观察预期RED，再写最小GREEN。用户要求
> 本任务不使用子代理。

**目标：** 在阶段5本地模拟链路中增加SQLite持久Inbox/Outbox/Audit、原子去重、
重放窗口、发送重试、死信、会话级并发、AI/人工所有权和重启恢复。

**架构：** 默认FastAPI应用使用`ReliablePddSimulatorService`；
`SQLiteReliabilityStore`是扩展自有持久账本；`MockPddAdapter`模拟幂等外部平台
和可控失败；`ConversationLockRegistry`只负责单进程会话顺序。阶段5简单服务
继续保留并回归。

**技术栈：** Python 3.11标准库`sqlite3`和`asyncio`、FastAPI、Pydantic v2、
pytest、Ruff、mypy；不新增依赖或Docker服务。

## 全局约束

- 设计基线：`docs/weekend-run/phase-06-design.md`，提交`e91287d`。
- 只使用明确合成的`FAKE/TEST`消息和临时SQLite文件。
- 不调用真实PDD、TGO业务API、模型、生产数据库或外部网络。
- 不猜测真实PDD dedupe key、幂等Header、查询接口或错误码。
- 不修改`repos/*`、根Compose、根Makefile或依赖锁文件。
- 不实现阶段7知识框架或阶段8完整风险/人工转接状态机。
- 不删除任何数据库、Docker卷或失败现场。
- 每个RED、GREEN、故障和修复写入
  `docs/weekend-run/logs/phase-06-validation.md`。

## 文件结构

预计创建：

```text
extensions/pdd-customer-service/app/models/reliability.py
extensions/pdd-customer-service/app/repositories/reliability.py
extensions/pdd-customer-service/app/repositories/sql/001_reliability.sql
extensions/pdd-customer-service/app/services/reliability.py
extensions/pdd-customer-service/tests/unit/test_reliability_models.py
extensions/pdd-customer-service/tests/unit/test_reliability_store.py
extensions/pdd-customer-service/tests/unit/test_reliable_service.py
extensions/pdd-customer-service/tests/integration/test_reliability_api.py
extensions/pdd-customer-service/tests/fixtures/reliability.py
docs/runbooks/message-reliability.md
docs/weekend-run/logs/phase-06-validation.md
docs/weekend-run/phase-06-report.md
```

预计修改：

```text
extensions/pdd-customer-service/.env.example
extensions/pdd-customer-service/app/adapters/pdd/mock.py
extensions/pdd-customer-service/app/adapters/pdd/__init__.py
extensions/pdd-customer-service/app/api/simulator.py
extensions/pdd-customer-service/app/main.py
extensions/pdd-customer-service/app/models/messages.py
extensions/pdd-customer-service/app/models/__init__.py
extensions/pdd-customer-service/app/repositories/__init__.py
extensions/pdd-customer-service/app/services/__init__.py
extensions/pdd-customer-service/tests/conftest.py
extensions/pdd-customer-service/tests/unit/test_pdd_adapters.py
extensions/pdd-customer-service/docs/runbooks/development.md
```

---

### 任务1：可靠性模型、重试策略和重放窗口

**文件：**

- 创建：`tests/unit/test_reliability_models.py`
- 创建：`app/models/reliability.py`
- 修改：`app/models/messages.py`
- 修改：`app/models/__init__.py`

**输出接口：**

```python
class MessageStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"

class ReplyOwner(StrEnum):
    AI = "ai"
    HUMAN = "human"

class MessageKey(BaseModel):
    model_config = ConfigDict(frozen=True)
    shop_id: Identifier
    message_id: Identifier

class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    send_timeout_seconds: float = 2.0
    replay_window_seconds: float = 300.0
    future_tolerance_seconds: float = 60.0
    def delay_after_failure(self, failed_attempt: int) -> float: ...
    def timestamp_reason(
        self,
        *,
        occurred_at: datetime,
        now: datetime,
    ) -> str | None: ...

class ReliabilityRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    inbox_id: int
    key: MessageKey
    conversation_key: ConversationKey
    occurred_at: AwareDatetime
    content: MessageText
    received_at: AwareDatetime
    trace_id: UUID
    reply_id: UUID
    reply_timestamp: AwareDatetime
    reply_content: MessageText
    status: MessageStatus
    attempts: int
    retryable: bool
    last_reason: str | None
    next_attempt_at: AwareDatetime | None
    lease_epoch: int | None
    inbound_recorded: bool
    conversation_created: bool

class AuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    audit_id: int
    trace_id: UUID
    event: str
    status: MessageStatus | None
    attempt: int
    reason: str | None
    created_at: AwareDatetime

class ClaimResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    record: ReliabilityRecord
    is_new: bool

class RecoverySummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    scanned: int
    sent: int
    failed: int
    dead_letter: int
```

`SimulationResult`增加默认字段：

```python
processing_status: MessageStatus = MessageStatus.SENT
duplicate: bool = False
attempts: int = 1
```

- [ ] **步骤1：写重试策略RED测试**

```python
@pytest.mark.unit
def test_retry_policy_uses_capped_exponential_delays() -> None:
    policy = RetryPolicy(
        max_attempts=4,
        base_delay_seconds=1,
        max_delay_seconds=3,
    )

    assert [policy.delay_after_failure(i) for i in (1, 2, 3)] == [1, 2, 3]
```

运行：

```bash
poetry run python -m pytest \
  tests/unit/test_reliability_models.py::test_retry_policy_uses_capped_exponential_delays -q
```

预期：无法导入`RetryPolicy`。

- [ ] **步骤2：实现最小枚举和RetryPolicy**

使用Pydantic冻结模型；`max_attempts`为1至10；所有秒数非负，
`send_timeout_seconds`必须大于0。指数计算为：

```python
min(
    self.base_delay_seconds * (2 ** (failed_attempt - 1)),
    self.max_delay_seconds,
)
```

- [ ] **步骤3：运行GREEN**

预期聚焦测试通过。

- [ ] **步骤4：写重放窗口RED测试**

固定`now=2026-07-18T09:05:00Z`，验证：

```python
assert policy.timestamp_reason(
    occurred_at=now - timedelta(seconds=301),
    now=now,
) == "message_too_old"
assert policy.timestamp_reason(
    occurred_at=now + timedelta(seconds=61),
    now=now,
) == "message_from_future"
assert policy.timestamp_reason(
    occurred_at=now - timedelta(seconds=300),
    now=now,
) is None
```

预期：方法尚不存在。

- [ ] **步骤5：实现窗口、持久模型和SimulationResult兼容字段**

`MessageKey`和会话模型使用现有标识约束。`ReliabilityRecord`必须保存恢复所需
请求、trace、reply、状态、尝试、lease epoch、retryable、原因和时间；正文只在
记录模型中，不进入`AuditRecord`。

- [ ] **步骤6：运行模型GREEN和阶段5回归**

```bash
poetry run python -m pytest \
  tests/unit/test_reliability_models.py \
  tests/unit/test_message_models.py \
  tests/unit/test_simulator_service.py -q
```

---

### 任务2：版本化SQLite Inbox/Outbox/Audit账本

**文件：**

- 创建：`app/repositories/sql/001_reliability.sql`
- 创建：`app/repositories/reliability.py`
- 创建：`tests/unit/test_reliability_store.py`
- 修改：`app/repositories/__init__.py`

**Schema必须完整包含：**

```sql
CREATE TABLE inbox_messages (
    inbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    content TEXT NOT NULL,
    received_at TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    inbound_recorded INTEGER NOT NULL DEFAULT 0,
    conversation_created INTEGER NOT NULL DEFAULT 0,
    UNIQUE (shop_id, message_id)
);

CREATE TABLE outbox_messages (
    reply_id TEXT PRIMARY KEY,
    inbox_id INTEGER NOT NULL UNIQUE REFERENCES inbox_messages(inbox_id),
    reply_timestamp TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    retryable INTEGER NOT NULL DEFAULT 1,
    last_reason TEXT,
    next_attempt_at TEXT,
    lease_epoch INTEGER
);

CREATE TABLE reply_leases (
    shop_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (shop_id, buyer_id, conversation_id)
);

CREATE TABLE audit_events (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    inbox_id INTEGER REFERENCES inbox_messages(inbox_id),
    trace_id TEXT NOT NULL,
    event TEXT NOT NULL,
    status TEXT,
    attempt INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);

PRAGMA user_version = 1;
```

**输出接口：**

```python
class PersistenceUnavailableError(RuntimeError): ...

class ReliabilityStore(Protocol):
    async def initialize(self) -> None: ...
    async def claim(...) -> ClaimResult: ...
    async def mark_inbound_recorded(...) -> ReliabilityRecord: ...
    async def mark_conversation_created(...) -> ReliabilityRecord: ...
    async def update_delivery(...) -> ReliabilityRecord: ...
    async def acquire_ai_lease(...) -> int | None: ...
    async def lease_is_current(...) -> bool: ...
    async def take_human_ownership(...) -> int: ...
    async def release_to_ai(...) -> int: ...
    async def recoverable(...) -> tuple[ReliabilityRecord, ...]: ...
    async def audit_for(...) -> tuple[AuditRecord, ...]: ...
    async def transcript(...) -> ConversationTranscript | None: ...

class SQLiteReliabilityStore:
    def __init__(self, database_path: Path, *, timeout_seconds: float = 0.2):
        ...
```

- [ ] **步骤1：写初始化和原子Claim RED**

使用`tmp_path / "reliability.sqlite3"`，显式`await initialize()`。同一请求调用
`claim`两次，断言第一次`is_new=True`、第二次`False`、两次记录的`trace_id`和
`reply_id`均为第一次值。

预期：无法导入仓库。

- [ ] **步骤2：实现schema初始化和Claim**

构造函数不得打开文件。公共异步方法通过`asyncio.to_thread`调用同步短事务；
连接使用`row_factory=sqlite3.Row`、`PRAGMA foreign_keys=ON`和有限timeout。
`INSERT OR IGNORE`与既有记录读取在同一`BEGIN IMMEDIATE`事务完成。重复时追加
`duplicate_detected`审计，但不覆盖原值。

- [ ] **步骤3：运行Claim GREEN**

```bash
poetry run python -m pytest \
  tests/unit/test_reliability_store.py::test_store_claims_message_once -q
```

- [ ] **步骤4：写状态、审计、重开和会话RED**

测试必须：

- 依次写`failed → retrying → sent`；
- 审计事件顺序包含`message_claimed`、`send_failed`、`retry_scheduled`、
  `reply_sent`；
- 关闭第一个仓库对象后用相同文件创建第二个对象；
- 第二对象读到`sent`且会话快照只有一条buyer和一条service。

- [ ] **步骤5：实现全部仓库接口**

所有状态更新与审计插入在同一事务。`transcript`按`inbox_id`排序，每条Inbox
显示一次buyer消息，只有`sent`Outbox显示service消息。所有
`sqlite3.OperationalError`转换为`PersistenceUnavailableError`且不包含SQL或
绝对路径。

- [ ] **步骤6：运行仓库GREEN**

```bash
poetry run python -m pytest tests/unit/test_reliability_store.py -q
```

---

### 任务3：可失败且幂等的Mock Adapter

**文件：**

- 修改：`app/adapters/pdd/mock.py`
- 修改：`app/adapters/pdd/__init__.py`
- 修改：`tests/unit/test_pdd_adapters.py`

**输出接口：**

```python
class MockPddSendError(RuntimeError): ...

class MockPddAdapter:
    def __init__(self, *, fail_send_attempts: int = 0) -> None: ...
    @property
    def send_attempt_count(self) -> int: ...
```

- [ ] **步骤1：写发送失败RED**

配置`fail_send_attempts=2`，连续发送相同Outbound三次：

```python
with pytest.raises(MockPddSendError):
    asyncio.run(adapter.send(outbound))
with pytest.raises(MockPddSendError):
    asyncio.run(adapter.send(outbound))
asyncio.run(adapter.send(outbound))
asyncio.run(adapter.send(outbound))

assert adapter.send_attempt_count == 4
assert adapter.outbound_count == 1
```

第四次使用相同`reply_id`不得重复追加买家视图。

- [ ] **步骤2：实现失败注入和reply_id幂等**

`send_attempt_count`每次调用增加；前N次抛固定异常；成功前检查已送达reply_id；
重复成功调用不追加、不增加`outbound_count`。

- [ ] **步骤3：写入站幂等RED并实现**

同一`shop_id + message_id`调用`receive`十次，断言`inbound_count==1`和会话中
buyer消息1条。实现只保存键集合，不推断真实PDD规则。

- [ ] **步骤4：运行Adapter GREEN和阶段5回归**

```bash
poetry run python -m pytest tests/unit/test_pdd_adapters.py -q
```

---

### 任务4：可靠处理器去重、重试、超时和死信

**文件：**

- 创建：`app/services/reliability.py`
- 创建：`tests/fixtures/reliability.py`
- 创建：`tests/unit/test_reliable_service.py`
- 修改：`app/services/__init__.py`

**输出接口：**

```python
class ReplayWindowError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

class ReliabilityUnavailableError(RuntimeError):
    """Raised when the durable reliability ledger is unavailable."""

class Clock(Protocol):
    def now(self) -> datetime: ...
    async def sleep(self, delay_seconds: float) -> None: ...

class SystemClock:
    def now(self) -> datetime: ...
    async def sleep(self, delay_seconds: float) -> None: ...

class ConversationLockRegistry:
    def lock_for(self, key: ConversationKey) -> asyncio.Lock: ...

class ReliablePddSimulatorService:
    async def process(
        self,
        request: PddTextMessageRequest,
    ) -> SimulationResult: ...
    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None: ...
    async def recover_pending(self) -> RecoverySummary: ...
    async def take_human_ownership(self, key: ConversationKey) -> int: ...
    async def release_to_ai(self, key: ConversationKey) -> int: ...
```

`tests/fixtures/reliability.py`提供显式测试辅助类型：

```python
class FakeClock:
    current: datetime
    sleeps: list[float]
    def now(self) -> datetime: ...
    async def sleep(self, delay_seconds: float) -> None: ...

class BlockingSendAdapter(MockPddAdapter): ...
class HangingSendAdapter(MockPddAdapter): ...
class FailOnceStore: ...
```

- [ ] **步骤1：写同一消息10次RED**

初始化真实SQLite仓库、真实内存会话仓库、Mock Adapter和FakeClock。顺序调用
`service.process(request)`十次，断言：

```python
assert adapter.inbound_count == 1
assert adapter.outbound_count == 1
assert repository.count == 1
assert results[0].duplicate is False
assert all(result.duplicate for result in results[1:])
assert all(result.processing_status is MessageStatus.SENT for result in results)
```

预期：可靠服务尚不存在。

- [ ] **步骤2：实现Claim、单次处理和重复结果**

处理顺序固定为：

```text
timestamp check
→ store.claim
→ duplicate short-circuit
→ conversation lock
→ acquire AI lease
→ adapter.receive
→ store.mark_inbound_recorded
→ conversation_repository.ensure
→ store.mark_conversation_created
→ send loop
```

数据库错误转成`ReliabilityUnavailableError`并记录固定fallback事件，不继续调用
Adapter。

- [ ] **步骤3：运行去重GREEN**

- [ ] **步骤4：写两失败一成功RED**

`MockPddAdapter(fail_send_attempts=2)`，断言attempt为3、状态`sent`、FakeClock
休眠为`[base_delay, base_delay * 2]`、会话service消息只有1条，审计含两次
`send_failed`和最终`reply_sent`。

- [ ] **步骤5：实现重试循环**

每次发送用`asyncio.wait_for`和相同reply_id。瞬时失败先写`failed`，再写
`retrying`和`next_attempt_at`；休眠后继续。成功写`sent`。

- [ ] **步骤6：写死信RED并实现**

失败次数大于等于`max_attempts`时：

```python
assert result.processing_status is MessageStatus.DEAD_LETTER
assert result.attempts == policy.max_attempts
assert adapter.outbound_count == 0
assert audits[-1].event == "dead_lettered"
```

- [ ] **步骤7：写真实超时RED并实现**

Hanging Adapter的`send`等待不返回，策略超时0.01秒、最大尝试1；断言最终
`dead_letter`，审计reason为`send_timeout`，测试总时长不使用长sleep。

- [ ] **步骤8：运行服务GREEN**

```bash
poetry run python -m pytest tests/unit/test_reliable_service.py -q
```

---

### 任务5：会话并发和AI/人工所有权

**文件：**

- 修改：`tests/unit/test_reliable_service.py`
- 修改：`app/services/reliability.py`

- [ ] **步骤1：写不同会话并行RED**

可控Adapter在`send`入口增加活动计数并等待测试释放。并发处理两个不同buyer的
请求，等待两个都进入后断言`max_active_sends==2`；释放后分别查询两个会话，
正文和回复不得串线。

- [ ] **步骤2：实现每完整会话键独立锁**

`ConversationLockRegistry.lock_for(key)`在短同步临界区创建并复用
`asyncio.Lock`。处理器只在Claim后获取对应锁，不使用全局业务锁。

- [ ] **步骤3：写同会话串行RED**

并发提交同一会话的两个不同message_id，第一个发送被阻塞时第二个不得进入发送；
释放后发送事件顺序必须为`message-001`、`message-002`，
`max_active_sends==1`。

- [ ] **步骤4：写人工阻止RED**

先调用`take_human_ownership`，再处理消息：

```python
assert result.processing_status is MessageStatus.FAILED
assert adapter.send_attempt_count == 0
assert audits[-1].reason == "human_owner_blocks_ai"
```

释放到AI后新消息允许发送；旧失败记录保持`retryable=false`，恢复扫描不发送。

- [ ] **步骤5：实现lease epoch二次检查**

Claim后取得AI epoch；每次发送前调用`lease_is_current`。人工接管在事务中设置
human并递增epoch；AI不得覆盖human。

- [ ] **步骤6：运行并发和所有权GREEN**

聚焦测试与完整`test_reliable_service.py`全部通过。

---

### 任务6：重启恢复、数据库不可用和默认API装配

**文件：**

- 修改：`app/services/reliability.py`
- 修改：`app/api/simulator.py`
- 修改：`app/main.py`
- 修改：`tests/conftest.py`
- 创建：`tests/integration/test_reliability_api.py`
- 修改：`.env.example`

- [ ] **步骤1：写重启恢复RED**

使用阻塞FakeClock：

1. 第一次发送失败后进入`retrying`并停在sleep；
2. 取消旧task；
3. 使用相同SQLite文件、同一个Mock Adapter和新服务对象；
4. 调用`recover_pending()`；
5. 断言恢复1项、最终sent、attempt为2、买家只看到1条service回复。

- [ ] **步骤2：实现recover_pending**

读取到期且`retryable=true`的`pending/failed/retrying`，按会话锁恢复。复用持久
trace、reply_id和attempts；不重新Claim，不恢复sent/dead_letter/human阻止项。

- [ ] **步骤3：写数据库暂不可用RED**

`FailOnceStore`第一次`claim`抛`PersistenceUnavailableError`：

```python
with pytest.raises(ReliabilityUnavailableError):
    asyncio.run(service.process(request))
assert adapter.inbound_count == 0
assert adapter.send_attempt_count == 0
assert "reliability_database_unavailable" in caplog.messages
```

第二次使用同一请求成功，证明没有无账本副作用。

- [ ] **步骤4：实现fallback审计**

固定日志事件只带trace、operation和`database_unavailable`原因，不带正文、SQL或
数据库路径。任何持久方法失败都停止当前发送循环。

- [ ] **步骤5：写API RED**

测试：

- 首次POST为201、状态sent、duplicate=false；
- 相同请求第二次为201、duplicate=true，Adapter入站和出站仍各1；
- 过期请求为409且无Adapter调用；
- claim不可用为503且响应不含路径/SQL；
- 用相同SQLite文件创建第二个App后GET仍返回两条消息。

- [ ] **步骤6：实现默认可靠装配和lifespan**

`create_simulator_router`接受同时兼容阶段5/阶段6的Protocol，捕获
`ReplayWindowError`为409、`ReliabilityUnavailableError`为503。

`create_app`增加关键字注入：

```python
reliability_store: ReliabilityStore | None = None
retry_policy: RetryPolicy | None = None
clock: Clock | None = None
```

默认仓库路径来自空安全变量`PDD_RELIABILITY_DB_PATH`，未设置时使用扩展
`.local/pdd-reliability.sqlite3`。构造不访问文件；lifespan执行initialize和
recover。测试fixture使用`tmp_path`、Fixed/FakeClock，不写仓库工作树数据库。

- [ ] **步骤7：运行API GREEN和阶段5全量回归**

```bash
poetry run python -m pytest tests/integration/test_reliability_api.py -q
poetry run python -m pytest -q
```

---

### 任务7：运行手册、最终门禁、提交和发布

**文件：**

- 创建：`docs/runbooks/message-reliability.md`
- 创建：`docs/weekend-run/logs/phase-06-validation.md`
- 创建：`docs/weekend-run/phase-06-report.md`
- 修改：`extensions/pdd-customer-service/docs/runbooks/development.md`

- [ ] **步骤1：实际进程验收**

在验证容器使用临时Git忽略SQLite路径启动服务，执行：

- 同一POST 10次；
- GET会话；
- 停止服务；
- 使用同一数据库重新启动；
- 再次GET。

验收：首次和重启后会话均只有1条buyer和1条service；数据库文件及sidecar均被
Git忽略；验收后精确停止扩展进程。

- [ ] **步骤2：编写可靠性运行手册**

必须包括：

- schema初始化、启动、停止和健康命令；
- 状态含义、默认重试参数和重放窗口；
- SQLite备份只读检查方式，不提供删除命令；
- dead_letter和人工阻止诊断；
- 数据库不可用503和fallback日志；
- 重启恢复；
- 单进程SQLite限制；
- 所有数据为FAKE/TEST，真实PDD幂等合同仍未配置。

- [ ] **步骤3：运行全部质量命令**

```bash
make format
make lint
make test-unit
make test-integration
make test
make security-check
```

预期格式、Ruff、mypy、单元、集成、契约、Bandit、pip-audit和`.env`忽略全部
通过。

- [ ] **步骤4：安全与边界门禁**

```bash
git diff --check
git diff --name-only phase-05-complete -- repos
git status --short -- repos
git check-ignore -v .local/pdd-reliability.sqlite3
```

受控源码Gitleaks总数不得超过22，阶段6差异必须为0；候选值不得输出。确认新增
依赖0、TGO核心变化0、SQLite schema脚本只在扩展内。

- [ ] **步骤5：创建报告**

报告记录RED/GREEN、并发证据、重试时间、恢复、503、死信、schema版本、测试
数量、Docker状态、依赖、核心变化、Gitleaks和无破坏回滚命令。

- [ ] **步骤6：最终提交、标签和推送**

提交：

```text
feat: add idempotent message processing and retries
```

标签：

```text
phase-06-complete
```

确认本地和远程无同名标签后，推送`phase/06-message-reliability`和标签到
`origin`。禁止强推、PR和主分支合并。远程分支、标签和本地HEAD必须指向同一
提交。

- [ ] **步骤7：进入阶段7门禁**

只有阶段6全部PASS、远程引用一致且工作区干净，才从`phase-06-complete`创建
`phase/07-knowledge-framework`。
