"""Unit tests for handoff orchestration and AI/human exclusion."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.pdd import MockPddAdapter
from app.models import (
    ConversationKey,
    ConversationMode,
    HandoffReason,
    HandoffRiskLevel,
    KnowledgeAvailability,
    MessageStatus,
    PddTextMessageRequest,
    ReliabilityRecord,
    RoutingAction,
    RoutingContext,
)
from app.repositories import (
    InMemoryConversationRepository,
    SQLiteHandoffRepository,
    SQLiteReliabilityStore,
)
from app.services import HandoffService, ReliablePddSimulatorService, RiskRuleEngine
from tests.fixtures.reliability import FakeClock

REPOSITORY_ROOT = Path(__file__).parents[4]
TRANSFER_RULES_PATH = REPOSITORY_ROOT / "config" / "pdd" / "transfer_rules.yml"
FORBIDDEN_CLAIMS_PATH = REPOSITORY_ROOT / "config" / "pdd" / "forbidden_claims.yml"
NOW = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
KEY = ConversationKey(
    shop_id="fake-shop",
    buyer_id="fake-buyer",
    conversation_id="fake-conversation",
)


class HandoffBeforeSendStore(SQLiteReliabilityStore):
    """Trigger a real handoff after AI lease acquisition but before send."""

    def __init__(
        self,
        database_path: Path,
        handoff_repository: SQLiteHandoffRepository,
    ) -> None:
        super().__init__(database_path)
        self._handoff_repository = handoff_repository

    async def mark_conversation_created(
        self,
        inbox_id: int,
        *,
        conversation_created: bool,
        recorded_at: datetime,
    ) -> ReliabilityRecord:
        record = await super().mark_conversation_created(
            inbox_id,
            conversation_created=conversation_created,
            recorded_at=recorded_at,
        )
        await self._handoff_repository.request_handoff(
            record.conversation_key,
            reason=HandoffReason.HUMAN_REQUESTED,
            risk_level=HandoffRiskLevel.MEDIUM,
            operator="test-race-router",
            occurred_at=recorded_at,
        )
        return record


def context(
    *,
    key: ConversationKey = KEY,
    message_text: str = "你好",
    knowledge_status: KnowledgeAvailability = KnowledgeAvailability.VALID,
) -> RoutingContext:
    return RoutingContext(
        conversation_key=key,
        message_text=message_text,
        knowledge_status=knowledge_status,
        service_available=True,
        unresolved_count=0,
        candidate_reply=None,
    )


def handoff_service(repository: SQLiteHandoffRepository) -> HandoffService:
    return HandoffService(
        repository=repository,
        engine=RiskRuleEngine.from_files(
            TRANSFER_RULES_PATH,
            FORBIDDEN_CLAIMS_PATH,
        ),
        clock=FakeClock(NOW),
    )


@pytest.mark.unit
def test_handoff_service_persists_risky_route_and_keeps_safe_route_in_ai(
    tmp_path: Path,
) -> None:
    repository = SQLiteHandoffRepository(tmp_path / "connector.sqlite3")
    asyncio.run(repository.initialize())
    service = handoff_service(repository)

    safe_key = KEY.model_copy(update={"conversation_id": "fake-safe"})
    safe = asyncio.run(service.evaluate_and_route(context(key=safe_key)))
    risky = asyncio.run(
        service.evaluate_and_route(
            context(message_text="我要退款"),
        )
    )
    safe_state = asyncio.run(service.state(safe_key))
    risky_state = asyncio.run(service.state(KEY))
    queue = asyncio.run(service.queue())
    audit = asyncio.run(repository.audit_for(KEY))

    assert safe_state is not None
    assert risky_state is not None
    assert safe.action is RoutingAction.CONTINUE_AI
    assert safe_state.mode is ConversationMode.AI
    assert risky.action is RoutingAction.HANDOFF
    assert risky.reason is HandoffReason.REFUND_COMPENSATION_PRICE
    assert risky.response_text == service.handoff_message
    assert risky_state.mode is ConversationMode.WAITING_HUMAN
    assert len(queue) == 1
    assert queue[0].risk_level is HandoffRiskLevel.HIGH
    assert [event.event for event in audit] == [
        "conversation_initialized",
        "handoff_requested",
    ]
    assert all("message_text" not in event.model_dump() for event in audit)


@pytest.mark.unit
def test_waiting_mode_blocks_ai_even_if_legacy_lease_is_released(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "connector.sqlite3"
    handoff_repository = SQLiteHandoffRepository(database_path)
    reliability_store = SQLiteReliabilityStore(database_path)
    asyncio.run(reliability_store.initialize())
    asyncio.run(handoff_repository.initialize())
    asyncio.run(
        handoff_repository.request_handoff(
            KEY,
            reason=HandoffReason.HUMAN_REQUESTED,
            risk_level=HandoffRiskLevel.MEDIUM,
            operator="test-router",
            occurred_at=NOW,
        )
    )
    asyncio.run(reliability_store.release_to_ai(KEY, recorded_at=NOW))
    adapter = MockPddAdapter()
    reliable_service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=InMemoryConversationRepository(),
        store=reliability_store,
        clock=FakeClock(NOW),
    )
    request = PddTextMessageRequest(
        message_id="fake-message",
        shop_id=KEY.shop_id,
        buyer_id=KEY.buyer_id,
        conversation_id=KEY.conversation_id,
        timestamp=NOW,
        content="人工等待期间的新消息",
    )

    result = asyncio.run(reliable_service.process(request))

    assert result.processing_status is MessageStatus.FAILED
    assert adapter.inbound_count == 0
    assert adapter.send_attempt_count == 0


@pytest.mark.unit
def test_handoff_transaction_revokes_ai_epoch_before_outbound_send(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "connector.sqlite3"
    handoff_repository = SQLiteHandoffRepository(database_path)
    store = HandoffBeforeSendStore(database_path, handoff_repository)
    asyncio.run(store.initialize())
    asyncio.run(handoff_repository.initialize())
    adapter = MockPddAdapter()
    reliable_service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=InMemoryConversationRepository(),
        store=store,
        clock=FakeClock(NOW),
    )
    request = PddTextMessageRequest(
        message_id="fake-race-message",
        shop_id=KEY.shop_id,
        buyer_id=KEY.buyer_id,
        conversation_id=KEY.conversation_id,
        timestamp=NOW,
        content="触发发送前人工接管",
    )

    result = asyncio.run(reliable_service.process(request))
    queue = asyncio.run(handoff_repository.queue())
    handoff_audit = asyncio.run(handoff_repository.audit_for(KEY))
    reliability_audit = asyncio.run(store.audit_for(1))

    assert result.processing_status is MessageStatus.FAILED
    assert adapter.inbound_count == 1
    assert adapter.send_attempt_count == 0
    assert len(queue) == 1
    assert handoff_audit[-1].event == "handoff_requested"
    assert reliability_audit[-1].event == "ai_reply_blocked"
