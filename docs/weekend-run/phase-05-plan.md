# 阶段5实施计划：本地PDD消息模拟器

> **执行规范：** 使用`superpowers:executing-plans`逐项执行；每个行为必须使用
> `superpowers:test-driven-development`先观察预期RED，再写最小GREEN实现。

**目标：** 在现有PDD扩展内实现无外部依赖的模拟入站、标准化、本地会话、固定
回复和买家会话查询链路。

**架构：** FastAPI只负责传输校验；`PddSimulatorService`编排
`PddAdapter`和本地会话仓库；`MockPddAdapter`保存合成收发记录；
`RealPddAdapter`保持显式未配置。所有依赖通过应用工厂注入，测试使用真实内存
组件而不是模拟业务行为。

**技术栈：** Python 3.11、FastAPI、Pydantic v2、pytest、Ruff、mypy。

## 全局约束

- 设计基线：`docs/weekend-run/phase-05-design.md`，提交`5e217b8`。
- 只使用明确合成的`FAKE/TEST`数据。
- 不调用真实PDD、真实TGO业务API、真实模型、数据库或外部网络。
- 不猜测PDD URL、Webhook、签名、事件名、错误码或发送协议。
- 不新增依赖、Docker服务或TGO核心修改。
- 不实现阶段6的去重、重试、死信、持久恢复和并发串行化。
- 普通日志不记录消息正文、凭据或完整外部负载。
- 每个RED和GREEN结果写入
  `docs/weekend-run/logs/phase-05-validation.md`。

## 文件结构

预计创建：

```text
extensions/pdd-customer-service/app/models/messages.py
extensions/pdd-customer-service/app/adapters/pdd/base.py
extensions/pdd-customer-service/app/adapters/pdd/mock.py
extensions/pdd-customer-service/app/adapters/pdd/real.py
extensions/pdd-customer-service/app/repositories/conversations.py
extensions/pdd-customer-service/app/services/simulator.py
extensions/pdd-customer-service/app/api/simulator.py
extensions/pdd-customer-service/tests/unit/test_message_models.py
extensions/pdd-customer-service/tests/unit/test_pdd_adapters.py
extensions/pdd-customer-service/tests/unit/test_conversation_repository.py
extensions/pdd-customer-service/tests/unit/test_simulator_service.py
extensions/pdd-customer-service/tests/integration/test_simulator_api.py
extensions/pdd-customer-service/tests/contract/test_real_pdd_disabled.py
docs/runbooks/pdd-simulator.md
docs/weekend-run/logs/phase-05-validation.md
docs/weekend-run/phase-05-report.md
```

预计修改：

```text
extensions/pdd-customer-service/app/models/__init__.py
extensions/pdd-customer-service/app/adapters/pdd/__init__.py
extensions/pdd-customer-service/app/repositories/__init__.py
extensions/pdd-customer-service/app/services/__init__.py
extensions/pdd-customer-service/app/main.py
extensions/pdd-customer-service/tests/conftest.py
extensions/pdd-customer-service/docs/runbooks/development.md
```

不修改`repos/*`、根Compose、根Makefile或依赖锁文件。

---

### 任务1：标准消息模型

**文件：**

- 创建：`extensions/pdd-customer-service/tests/unit/test_message_models.py`
- 创建：`extensions/pdd-customer-service/app/models/messages.py`
- 修改：`extensions/pdd-customer-service/app/models/__init__.py`

**输出接口：**

- `PddTextMessageRequest`
- `ConversationKey`
- `NormalizedMessage`
- `OutboundMessage`
- `ConversationMessage`
- `ConversationTranscript`
- `SimulationResult`

- [ ] **步骤1：写模型RED测试**

测试必须证明六个请求字段可解析、标识会去除首尾空白、无时区时间被拒绝、空正文
和超过4000字符正文被拒绝、会话键可哈希。

```python
"""Unit tests for typed simulator message models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import ConversationKey, PddTextMessageRequest


@pytest.mark.unit
def test_simulated_text_request_normalizes_identifiers() -> None:
    request = PddTextMessageRequest(
        message_id=" message-001 ",
        shop_id=" shop-test ",
        buyer_id=" buyer-test ",
        conversation_id=" conversation-test ",
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
        content="你好",
    )

    assert request.message_id == "message-001"
    assert request.shop_id == "shop-test"
    assert request.buyer_id == "buyer-test"
    assert request.conversation_id == "conversation-test"
    assert request.content == "你好"


@pytest.mark.unit
def test_simulated_text_request_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        PddTextMessageRequest(
            message_id="message-001",
            shop_id="shop-test",
            buyer_id="buyer-test",
            conversation_id="conversation-test",
            timestamp=datetime(2026, 7, 18, 9, 0),
            content="你好",
        )


@pytest.mark.unit
@pytest.mark.parametrize("content", ["", " " * 4, "测" * 4001])
def test_simulated_text_request_rejects_invalid_content(content: str) -> None:
    with pytest.raises(ValidationError):
        PddTextMessageRequest(
            message_id="message-001",
            shop_id="shop-test",
            buyer_id="buyer-test",
            conversation_id="conversation-test",
            timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
            content=content,
        )


@pytest.mark.unit
def test_conversation_key_is_stable_and_hashable() -> None:
    first = ConversationKey(
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
    )
    second = ConversationKey(
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
    )

    assert first == second
    assert {first, second} == {first}
```

- [ ] **步骤2：运行RED**

```bash
poetry run python -m pytest tests/unit/test_message_models.py -q
```

预期：收集失败，提示无法从`app.models`导入新增模型。

- [ ] **步骤3：实现最小模型**

`messages.py`使用`StringConstraints`、`AwareDatetime`、`ConfigDict`和明确
`Literal`：

```python
"""Typed models for the local PDD message simulator."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class ConversationKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shop_id: Identifier
    buyer_id: Identifier
    conversation_id: Identifier


class PddTextMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: Identifier
    shop_id: Identifier
    buyer_id: Identifier
    conversation_id: Identifier
    timestamp: AwareDatetime
    content: MessageText


class NormalizedMessage(PddTextMessageRequest):
    received_at: AwareDatetime
    trace_id: UUID
    source: Literal["mock-pdd"] = "mock-pdd"


class OutboundMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reply_id: UUID
    trace_id: UUID
    shop_id: Identifier
    buyer_id: Identifier
    conversation_id: Identifier
    in_reply_to_message_id: Identifier
    timestamp: AwareDatetime
    content: MessageText


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Literal["buyer", "service"]
    message_id: Identifier
    timestamp: AwareDatetime
    content: MessageText


class ConversationTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: ConversationKey
    messages: tuple[ConversationMessage, ...]


class SimulationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: UUID
    conversation_created: bool
    normalized_message: NormalizedMessage
    outbound_message: OutboundMessage
```

`app/models/__init__.py`显式导出全部新增类型，不使用通配导入。

- [ ] **步骤4：运行GREEN和模型回归**

```bash
poetry run python -m pytest tests/unit/test_message_models.py tests/unit/test_health.py -q
```

预期：模型测试和原健康单元测试全部通过。

---

### 任务2：Mock和禁用的Real Adapter

**文件：**

- 创建：`extensions/pdd-customer-service/tests/unit/test_pdd_adapters.py`
- 创建：`extensions/pdd-customer-service/tests/contract/test_real_pdd_disabled.py`
- 创建：`extensions/pdd-customer-service/app/adapters/pdd/base.py`
- 创建：`extensions/pdd-customer-service/app/adapters/pdd/mock.py`
- 创建：`extensions/pdd-customer-service/app/adapters/pdd/real.py`
- 修改：`extensions/pdd-customer-service/app/adapters/pdd/__init__.py`

**输入：** 任务1的`NormalizedMessage`、`OutboundMessage`、
`ConversationKey`和`ConversationTranscript`。

**输出：** `PddAdapter`、`MockPddAdapter`、`RealPddAdapter`和
`RealPddNotConfiguredError`。

- [ ] **步骤1：写Adapter RED测试**

测试使用`asyncio.run`，不增加`pytest-asyncio`依赖：

```python
"""Unit tests for local and disabled PDD adapters."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.adapters.pdd import MockPddAdapter
from app.models import ConversationKey, NormalizedMessage, OutboundMessage


def build_message() -> NormalizedMessage:
    now = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)
    return NormalizedMessage(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=now,
        content="你好",
        received_at=now,
        trace_id=uuid4(),
    )


@pytest.mark.unit
def test_mock_adapter_records_one_inbound_and_one_outbound() -> None:
    adapter = MockPddAdapter()
    inbound = build_message()
    outbound = OutboundMessage(
        reply_id=uuid4(),
        trace_id=inbound.trace_id,
        shop_id=inbound.shop_id,
        buyer_id=inbound.buyer_id,
        conversation_id=inbound.conversation_id,
        in_reply_to_message_id=inbound.message_id,
        timestamp=inbound.timestamp,
        content="已收到测试消息",
    )
    key = ConversationKey(
        shop_id=inbound.shop_id,
        buyer_id=inbound.buyer_id,
        conversation_id=inbound.conversation_id,
    )

    asyncio.run(adapter.receive(inbound))
    asyncio.run(adapter.send(outbound))
    transcript = asyncio.run(adapter.transcript(key))

    assert adapter.inbound_count == 1
    assert adapter.outbound_count == 1
    assert transcript is not None
    assert [item.direction for item in transcript.messages] == ["buyer", "service"]
    assert [item.content for item in transcript.messages] == [
        "你好",
        "已收到测试消息",
    ]
```

契约测试：

```python
"""Contract guard that keeps the real PDD adapter disabled."""

import asyncio

import pytest

from app.adapters.pdd import RealPddAdapter, RealPddNotConfiguredError
from app.models import ConversationKey


@pytest.mark.contract
def test_real_pdd_adapter_cannot_be_used_without_official_contract() -> None:
    adapter = RealPddAdapter()
    key = ConversationKey(
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
    )

    with pytest.raises(RealPddNotConfiguredError):
        asyncio.run(adapter.transcript(key))
```

- [ ] **步骤2：运行RED**

```bash
poetry run python -m pytest \
  tests/unit/test_pdd_adapters.py \
  tests/contract/test_real_pdd_disabled.py -q
```

预期：无法导入新增Adapter。

- [ ] **步骤3：实现Adapter**

`base.py`：

```python
"""PDD adapter contract independent of any real protocol."""

from typing import Protocol

from app.models import (
    ConversationKey,
    ConversationTranscript,
    NormalizedMessage,
    OutboundMessage,
)


class PddAdapter(Protocol):
    async def receive(self, message: NormalizedMessage) -> None: ...

    async def send(self, message: OutboundMessage) -> None: ...

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None: ...
```

`MockPddAdapter`内部使用
`dict[ConversationKey, list[ConversationMessage]]`，只读属性返回累计入站和
出站计数。`receive`和`send`各追加一次，`transcript`返回tuple快照。

`RealPddAdapter`的三个正式接口都立即抛出：

```python
class RealPddNotConfiguredError(RuntimeError):
    """Raised because no official PDD contract is configured."""


class RealPddAdapter:
    async def receive(self, message: NormalizedMessage) -> None:
        raise RealPddNotConfiguredError("Real PDD integration is not configured")

    async def send(self, message: OutboundMessage) -> None:
        raise RealPddNotConfiguredError("Real PDD integration is not configured")

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None:
        raise RealPddNotConfiguredError("Real PDD integration is not configured")
```

生产文件不出现网络库、URL、Header、签名或真实协议字段。

- [ ] **步骤4：运行GREEN**

```bash
poetry run python -m pytest \
  tests/unit/test_pdd_adapters.py \
  tests/contract/test_real_pdd_disabled.py -q
```

预期：Adapter和禁用契约测试全部通过。

---

### 任务3：本地会话仓库

**文件：**

- 创建：`extensions/pdd-customer-service/tests/unit/test_conversation_repository.py`
- 创建：`extensions/pdd-customer-service/app/repositories/conversations.py`
- 修改：`extensions/pdd-customer-service/app/repositories/__init__.py`

**输出接口：**

```python
async def ensure(key: ConversationKey, *, created_at: datetime) -> bool
```

返回`True`表示新建，`False`表示关联既有会话。

- [ ] **步骤1：写仓库RED测试**

```python
"""Unit tests for local simulator conversation association."""

import asyncio
from datetime import datetime, timezone

import pytest

from app.models import ConversationKey
from app.repositories import InMemoryConversationRepository


@pytest.mark.unit
def test_repository_creates_then_reuses_exact_conversation_key() -> None:
    repository = InMemoryConversationRepository()
    key = ConversationKey(
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
    )
    now = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)

    assert asyncio.run(repository.ensure(key, created_at=now)) is True
    assert asyncio.run(repository.ensure(key, created_at=now)) is False
    assert repository.count == 1


@pytest.mark.unit
def test_repository_does_not_mix_same_id_across_buyers_or_shops() -> None:
    repository = InMemoryConversationRepository()
    now = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)
    keys = (
        ConversationKey(shop_id="shop-a", buyer_id="buyer-a", conversation_id="c"),
        ConversationKey(shop_id="shop-a", buyer_id="buyer-b", conversation_id="c"),
        ConversationKey(shop_id="shop-b", buyer_id="buyer-a", conversation_id="c"),
    )

    assert all(
        asyncio.run(repository.ensure(key, created_at=now)) for key in keys
    )
    assert repository.count == 3
```

- [ ] **步骤2：运行RED**

```bash
poetry run python -m pytest tests/unit/test_conversation_repository.py -q
```

预期：无法导入`InMemoryConversationRepository`。

- [ ] **步骤3：实现仓库**

使用`dict[ConversationKey, datetime]`保存创建时间；`ensure`只判断和插入完整键，
不做持久化、锁、去重或重试。定义同签名`ConversationRepository` Protocol。

- [ ] **步骤4：运行GREEN**

```bash
poetry run python -m pytest tests/unit/test_conversation_repository.py -q
```

预期：创建、复用和隔离测试全部通过。

---

### 任务4：模拟消息编排服务

**文件：**

- 创建：`extensions/pdd-customer-service/tests/unit/test_simulator_service.py`
- 创建：`extensions/pdd-customer-service/app/services/simulator.py`
- 修改：`extensions/pdd-customer-service/app/services/__init__.py`

**输入：** `PddAdapter`、`ConversationRepository`和任务1模型。

**输出：**

```python
FIXED_REPLY = "已收到测试消息"
async def process(request: PddTextMessageRequest) -> SimulationResult
async def transcript(key: ConversationKey) -> ConversationTranscript | None
```

- [ ] **步骤1：写服务RED测试**

使用真实`MockPddAdapter`和真实内存仓库：

```python
"""Unit tests for simulator message orchestration."""

import asyncio
import logging
from datetime import datetime, timezone

import pytest

from app.adapters.pdd import MockPddAdapter
from app.models import PddTextMessageRequest
from app.repositories import InMemoryConversationRepository
from app.services import FIXED_REPLY, PddSimulatorService


@pytest.mark.unit
def test_service_processes_one_message_and_emits_traceable_safe_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = MockPddAdapter()
    repository = InMemoryConversationRepository()
    service = PddSimulatorService(adapter=adapter, repository=repository)
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
        content="你好",
    )

    with caplog.at_level(logging.INFO):
        result = asyncio.run(service.process(request))

    assert result.conversation_created is True
    assert result.outbound_message.content == FIXED_REPLY
    assert result.outbound_message.in_reply_to_message_id == "message-001"
    assert adapter.inbound_count == 1
    assert adapter.outbound_count == 1
    assert repository.count == 1
    assert "你好" not in caplog.text
    assert {record.getMessage() for record in caplog.records} == {
        "mock_pdd_message_received",
        "mock_pdd_reply_sent",
    }
    assert all(
        getattr(record, "trace_id", None) == str(result.trace_id)
        for record in caplog.records
    )
```

同一完整会话键的第二条不同`message_id`必须复用会话：

```python
@pytest.mark.unit
def test_service_reuses_the_exact_conversation_key() -> None:
    adapter = MockPddAdapter()
    repository = InMemoryConversationRepository()
    service = PddSimulatorService(adapter=adapter, repository=repository)
    first = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
        content="第一条测试消息",
    )
    second = first.model_copy(
        update={
            "message_id": "message-002",
            "content": "第二条测试消息",
        }
    )

    first_result = asyncio.run(service.process(first))
    second_result = asyncio.run(service.process(second))

    assert first_result.conversation_created is True
    assert second_result.conversation_created is False
    assert repository.count == 1
    assert adapter.inbound_count == 2
    assert adapter.outbound_count == 2
```

- [ ] **步骤2：运行RED**

```bash
poetry run python -m pytest tests/unit/test_simulator_service.py -q
```

预期：无法导入服务。

- [ ] **步骤3：实现最小服务**

`process`使用`datetime.now(timezone.utc)`和`uuid4()`构造标准消息、trace和reply。
严格顺序为`adapter.receive`、`repository.ensure`、构造固定回复、
`adapter.send`。两条INFO日志只通过`extra`记录：

```python
{
    "trace_id": str(trace_id),
    "message_id": request.message_id,
    "conversation_id": request.conversation_id,
    "direction": "inbound" | "outbound",
}
```

日志消息本身分别固定为`mock_pdd_message_received`和
`mock_pdd_reply_sent`，禁止包含`content`。

- [ ] **步骤4：运行GREEN和相关单元回归**

```bash
poetry run python -m pytest \
  tests/unit/test_message_models.py \
  tests/unit/test_pdd_adapters.py \
  tests/unit/test_conversation_repository.py \
  tests/unit/test_simulator_service.py -q
```

预期：全部通过。

---

### 任务5：FastAPI模拟入口和完整收发链路

**文件：**

- 创建：`extensions/pdd-customer-service/tests/integration/test_simulator_api.py`
- 创建：`extensions/pdd-customer-service/app/api/simulator.py`
- 修改：`extensions/pdd-customer-service/app/main.py`
- 修改：`extensions/pdd-customer-service/tests/conftest.py`

**HTTP接口：**

```text
POST /simulator/messages
GET /simulator/shops/{shop_id}/buyers/{buyer_id}/conversations/{conversation_id}
```

- [ ] **步骤1：写API RED测试**

`tests/conftest.py`新增`mock_pdd_adapter`和
`conversation_repository` fixture，并注入`create_app`。

完整链路测试：

```python
"""In-process HTTP tests for the complete local PDD simulator chain."""

import pytest
from fastapi.testclient import TestClient

from app.adapters.pdd import MockPddAdapter
from app.repositories import InMemoryConversationRepository


@pytest.mark.integration
def test_buyer_sends_hello_and_reads_fixed_reply(
    client: TestClient,
    mock_pdd_adapter: MockPddAdapter,
    conversation_repository: InMemoryConversationRepository,
) -> None:
    response = client.post(
        "/simulator/messages",
        json={
            "message_id": "message-001",
            "shop_id": "shop-test",
            "buyer_id": "buyer-test",
            "conversation_id": "conversation-test",
            "timestamp": "2026-07-18T09:00:00Z",
            "content": "你好",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["conversation_created"] is True
    assert body["outbound_message"]["content"] == "已收到测试消息"
    assert mock_pdd_adapter.inbound_count == 1
    assert mock_pdd_adapter.outbound_count == 1
    assert conversation_repository.count == 1

    transcript = client.get(
        "/simulator/shops/shop-test/buyers/buyer-test/"
        "conversations/conversation-test"
    )

    assert transcript.status_code == 200
    assert [
        (item["direction"], item["content"])
        for item in transcript.json()["messages"]
    ] == [
        ("buyer", "你好"),
        ("service", "已收到测试消息"),
    ]
```

未知完整会话键返回404，无时区时间返回422：

```python
@pytest.mark.integration
def test_unknown_conversation_returns_not_found(client: TestClient) -> None:
    response = client.get(
        "/simulator/shops/shop-test/buyers/buyer-test/"
        "conversations/missing-conversation"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


@pytest.mark.integration
def test_message_with_naive_timestamp_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/simulator/messages",
        json={
            "message_id": "message-001",
            "shop_id": "shop-test",
            "buyer_id": "buyer-test",
            "conversation_id": "conversation-test",
            "timestamp": "2026-07-18T09:00:00",
            "content": "你好",
        },
    )

    assert response.status_code == 422
```

- [ ] **步骤2：运行RED**

```bash
poetry run python -m pytest tests/integration/test_simulator_api.py -q
```

预期：POST返回404，因为模拟路由尚未装配。

- [ ] **步骤3：实现API和依赖注入**

`create_simulator_router(service)`创建路由闭包：

```python
router = APIRouter(prefix="/simulator", tags=["simulator"])

@router.post("/messages", response_model=SimulationResult, status_code=201)
async def process_message(
    message: PddTextMessageRequest,
) -> SimulationResult:
    return await service.process(message)
```

GET接收三个路径参数，构造`ConversationKey`后调用
`service.transcript`；结果为`None`时抛出404。

`create_app`新增仅限关键字的可选注入参数：

```python
def create_app(
    *,
    pdd_adapter: PddAdapter | None = None,
    conversation_repository: ConversationRepository | None = None,
) -> FastAPI:
```

默认分别使用`MockPddAdapter()`和
`InMemoryConversationRepository()`；装配健康路由和模拟路由。导入应用仍不得
连接网络、数据库、TGO、PDD或模型。

- [ ] **步骤4：运行GREEN和完整测试**

```bash
poetry run python -m pytest tests/integration/test_simulator_api.py -q
poetry run python -m pytest -q
```

预期：完整链路通过，原健康测试继续通过。

---

### 任务6：运行手册和阶段证据

**文件：**

- 创建：`docs/runbooks/pdd-simulator.md`
- 创建：`docs/weekend-run/logs/phase-05-validation.md`
- 创建：`docs/weekend-run/phase-05-report.md`
- 修改：`extensions/pdd-customer-service/docs/runbooks/development.md`

- [ ] **步骤1：实际启动扩展**

在现有Python 3.11验证容器中从扩展目录启动：

```bash
make run
```

服务必须绑定`127.0.0.1:8091`。使用本地HTTP客户端发送：

```json
{
  "message_id": "message-001",
  "shop_id": "shop-test",
  "buyer_id": "buyer-test",
  "conversation_id": "conversation-test",
  "timestamp": "2026-07-18T09:00:00Z",
  "content": "你好"
}
```

预期POST为201，固定回复为`已收到测试消息`；GET返回顺序正确的两条消息。

- [ ] **步骤2：编写运行手册**

`docs/runbooks/pdd-simulator.md`必须包含：

- 启动、停止、健康检查命令；
- PowerShell和curl的POST示例；
- 完整会话GET地址；
- 明确标注全部ID和文本为FAKE/TEST；
- Real Adapter未配置说明；
- 状态仅在进程内存、重启丢失的限制；
- 阶段6才处理去重、重试和恢复；
- 故障排查和日志脱敏规则。

- [ ] **步骤3：更新开发手册**

把“Phase 3只有健康接口”改为版本化范围说明：健康接口仍无依赖，Phase 5新增
本地模拟接口；开发手册链接新的模拟器运行手册。不更改统一Make命令。

- [ ] **步骤4：写验证日志和报告**

记录每个测试的RED原因、GREEN数量、运行时HTTP结果、格式/类型/安全结果、容器
状态、依赖变化、核心代码变化、Gitleaks数量和回滚命令。禁止把候选值、环境
密码或消息以外的真实数据写入文档。

---

### 任务7：阶段5最终验收、提交和发布

- [ ] **步骤1：运行全部质量命令**

从`extensions/pdd-customer-service/`执行：

```bash
make format
make lint
make test-unit
make test-integration
make test
make security-check
```

预期：

- Ruff格式和规则通过；
- mypy strict通过；
- 单元、集成、契约和全量测试全部通过；
- Bandit通过；
- pip-audit无已知漏洞；
- `.env`继续被忽略。

- [ ] **步骤2：运行安全和边界门禁**

```bash
git diff --check
git diff --name-only phase-04-complete..HEAD -- repos
git status --short
```

重新创建“受控HEAD + 阶段5文件”只读快照运行Gitleaks：

- 总候选不得超过22项既有基线；
- 阶段5新增文件候选必须为0；
- 只输出规则和文件路径，不输出值。

- [ ] **步骤3：核对验收场景**

必须有新鲜自动化证据证明：

- 输入`你好`；
- Adapter入站只发生1次；
- 正确创建本地会话；
- 固定回复严格匹配；
- GET买家视图看到回复；
- 日志可按trace追踪且不含正文；
- 不需要真实凭据或外部网络；
- `repos/*`修改为0。

- [ ] **步骤4：提交、标签和推送**

阶段最终提交信息：

```text
feat: add local pdd customer message simulator
```

创建：

```text
phase-05-complete
```

先确认本地和远程均不存在同名标签，再推送
`phase/05-pdd-simulator`和标签到`origin`。禁止强推、PR和主分支合并。

阶段通过且远程引用确认后，才从`phase-05-complete`创建
`phase/06-message-reliability`。
