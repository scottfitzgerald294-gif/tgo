"""Unit tests for durable, idempotent message processing."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.pdd import MockPddAdapter
from app.models import (
    ConversationKey,
    MessageStatus,
    PddTextMessageRequest,
    RetryPolicy,
    SimulationResult,
)
from app.repositories import InMemoryConversationRepository, SQLiteReliabilityStore
from app.services import (
    ReliabilityUnavailableError,
    ReliablePddSimulatorService,
    ReplayWindowError,
)
from tests.fixtures.reliability import (
    BlockingRetryClock,
    BlockingSendAdapter,
    FailOnceClaimStore,
    FailOnceInboundMarkStore,
    FakeClock,
    HangingSendAdapter,
    TakeoverAfterConversationStore,
)


@pytest.mark.unit
def test_reliable_service_processes_ten_duplicate_messages_once(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    adapter = MockPddAdapter()
    repository = InMemoryConversationRepository()
    store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=repository,
        store=store,
        clock=clock,
    )
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=clock.now(),
        content="你好",
    )

    results = [asyncio.run(service.process(request)) for _ in range(10)]

    assert adapter.inbound_count == 1
    assert adapter.outbound_count == 1
    assert repository.count == 1
    assert results[0].duplicate is False
    assert all(result.duplicate for result in results[1:])
    assert all(result.processing_status is MessageStatus.SENT for result in results)


@pytest.mark.unit
def test_reliable_service_retries_twice_then_sends_once(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    adapter = MockPddAdapter(fail_send_attempts=2)
    repository = InMemoryConversationRepository()
    store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=repository,
        store=store,
        clock=clock,
        retry_policy=RetryPolicy(
            max_attempts=3,
            base_delay_seconds=1,
            max_delay_seconds=10,
        ),
    )
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=clock.now(),
        content="你好",
    )

    result = asyncio.run(service.process(request))
    transcript = asyncio.run(
        service.transcript(
            ConversationKey(
                shop_id=request.shop_id,
                buyer_id=request.buyer_id,
                conversation_id=request.conversation_id,
            )
        )
    )
    audits = asyncio.run(store.audit_for(1))

    assert result.processing_status is MessageStatus.SENT
    assert result.attempts == 3
    assert clock.sleeps == [1, 2]
    assert adapter.send_attempt_count == 3
    assert adapter.outbound_count == 1
    assert transcript is not None
    assert [message.direction for message in transcript.messages].count("service") == 1
    assert [audit.event for audit in audits].count("send_failed") == 2
    assert audits[-1].event == "reply_sent"


@pytest.mark.unit
def test_reliable_service_moves_exhausted_send_to_dead_letter(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    adapter = MockPddAdapter(fail_send_attempts=5)
    store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=InMemoryConversationRepository(),
        store=store,
        clock=clock,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=1),
    )
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=clock.now(),
        content="你好",
    )

    result = asyncio.run(service.process(request))
    audits = asyncio.run(store.audit_for(1))

    assert result.processing_status is MessageStatus.DEAD_LETTER
    assert result.attempts == 3
    assert adapter.send_attempt_count == 3
    assert adapter.outbound_count == 0
    assert audits[-1].event == "dead_lettered"


@pytest.mark.unit
def test_reliable_service_times_out_hanging_send_and_dead_letters(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    adapter = HangingSendAdapter()
    store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=InMemoryConversationRepository(),
        store=store,
        clock=clock,
        retry_policy=RetryPolicy(max_attempts=1, send_timeout_seconds=0.01),
    )
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=clock.now(),
        content="你好",
    )

    async def run_with_test_guard() -> SimulationResult:
        return await asyncio.wait_for(service.process(request), timeout=0.2)

    result = asyncio.run(run_with_test_guard())
    audits = asyncio.run(store.audit_for(1))

    assert result.processing_status is MessageStatus.DEAD_LETTER
    assert result.attempts == 1
    assert adapter.send_attempt_count == 1
    assert adapter.outbound_count == 0
    assert audits[-1].reason == "send_timeout"


@pytest.mark.unit
def test_reliable_service_allows_distinct_conversations_to_send_in_parallel(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
        adapter = BlockingSendAdapter(expected_concurrent=2)
        store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
        await store.initialize()
        service = ReliablePddSimulatorService(
            adapter=adapter,
            repository=InMemoryConversationRepository(),
            store=store,
            clock=clock,
        )
        first = PddTextMessageRequest(
            message_id="message-001",
            shop_id="shop-test",
            buyer_id="buyer-a",
            conversation_id="conversation-a",
            timestamp=clock.now(),
            content="买家A",
        )
        second = first.model_copy(
            update={
                "message_id": "message-002",
                "buyer_id": "buyer-b",
                "conversation_id": "conversation-b",
                "content": "买家B",
            }
        )

        tasks = [
            asyncio.create_task(service.process(first)),
            asyncio.create_task(service.process(second)),
        ]
        await asyncio.wait_for(adapter.wait_until_expected_entered(), timeout=0.2)
        assert adapter.max_active_sends == 2
        adapter.release()
        await asyncio.gather(*tasks)
        first_transcript = await service.transcript(
            ConversationKey(
                shop_id=first.shop_id,
                buyer_id=first.buyer_id,
                conversation_id=first.conversation_id,
            )
        )
        second_transcript = await service.transcript(
            ConversationKey(
                shop_id=second.shop_id,
                buyer_id=second.buyer_id,
                conversation_id=second.conversation_id,
            )
        )
        assert first_transcript is not None
        assert second_transcript is not None
        assert first_transcript.messages[0].content == "买家A"
        assert second_transcript.messages[0].content == "买家B"

    asyncio.run(scenario())


@pytest.mark.unit
def test_reliable_service_serializes_messages_in_one_conversation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
        adapter = BlockingSendAdapter(expected_concurrent=1)
        store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
        await store.initialize()
        service = ReliablePddSimulatorService(
            adapter=adapter,
            repository=InMemoryConversationRepository(),
            store=store,
            clock=clock,
        )
        first = PddTextMessageRequest(
            message_id="message-001",
            shop_id="shop-test",
            buyer_id="buyer-test",
            conversation_id="conversation-test",
            timestamp=clock.now(),
            content="第一条",
        )
        second = first.model_copy(
            update={"message_id": "message-002", "content": "第二条"}
        )

        first_task = asyncio.create_task(service.process(first))
        await asyncio.wait_for(adapter.wait_until_expected_entered(), timeout=0.2)
        second_task = asyncio.create_task(service.process(second))
        await asyncio.sleep(0.02)

        assert adapter.send_order == ["message-001"]
        assert adapter.max_active_sends == 1
        adapter.release()
        await asyncio.gather(first_task, second_task)
        assert adapter.send_order == ["message-001", "message-002"]
        assert adapter.max_active_sends == 1

    asyncio.run(scenario())


@pytest.mark.unit
def test_reliable_service_human_owner_blocks_ai_until_explicit_release(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    adapter = MockPddAdapter()
    store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=InMemoryConversationRepository(),
        store=store,
        clock=clock,
    )
    key = ConversationKey(
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
    )
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id=key.shop_id,
        buyer_id=key.buyer_id,
        conversation_id=key.conversation_id,
        timestamp=clock.now(),
        content="你好",
    )

    asyncio.run(service.take_human_ownership(key))
    blocked = asyncio.run(service.process(request))
    blocked_audits = asyncio.run(store.audit_for(1))
    recoverable = asyncio.run(store.recoverable(now=clock.now()))

    assert blocked.processing_status is MessageStatus.FAILED
    assert blocked.attempts == 0
    assert adapter.inbound_count == 0
    assert adapter.send_attempt_count == 0
    assert blocked_audits[-1].reason == "human_owner_blocks_ai"
    assert recoverable == ()

    asyncio.run(service.release_to_ai(key))
    sent = asyncio.run(
        service.process(
            request.model_copy(
                update={"message_id": "message-002", "content": "恢复后消息"}
            )
        )
    )

    assert sent.processing_status is MessageStatus.SENT
    assert adapter.inbound_count == 1
    assert adapter.outbound_count == 1


@pytest.mark.unit
def test_reliable_service_stale_ai_epoch_cannot_send_after_human_takeover(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    adapter = MockPddAdapter()
    store = TakeoverAfterConversationStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=InMemoryConversationRepository(),
        store=store,
        clock=clock,
    )
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=clock.now(),
        content="接管竞态测试",
    )

    result = asyncio.run(service.process(request))
    audits = asyncio.run(store.audit_for(1))

    assert result.processing_status is MessageStatus.FAILED
    assert adapter.inbound_count == 1
    assert adapter.send_attempt_count == 0
    assert adapter.outbound_count == 0
    assert audits[-1].reason == "reply_lease_changed"


@pytest.mark.unit
def test_reliable_service_rejects_replayed_message_before_persistence(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 7, 18, 9, 5, 1, tzinfo=UTC))
    adapter = MockPddAdapter()
    store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=InMemoryConversationRepository(),
        store=store,
        clock=clock,
        retry_policy=RetryPolicy(replay_window_seconds=300),
    )
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        content="过期消息",
    )

    with pytest.raises(ReplayWindowError) as captured:
        asyncio.run(service.process(request))

    assert captured.value.reason == "message_too_old"
    assert adapter.inbound_count == 0
    assert adapter.send_attempt_count == 0
    assert asyncio.run(store.recoverable(now=clock.now())) == ()


@pytest.mark.unit
def test_reliable_service_recovers_retrying_message_after_restart(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database_path = tmp_path / "reliability.sqlite3"
        first_clock = BlockingRetryClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
        adapter = MockPddAdapter(fail_send_attempts=1)
        first_store = SQLiteReliabilityStore(database_path)
        await first_store.initialize()
        first_service = ReliablePddSimulatorService(
            adapter=adapter,
            repository=InMemoryConversationRepository(),
            store=first_store,
            clock=first_clock,
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=1),
        )
        request = PddTextMessageRequest(
            message_id="message-001",
            shop_id="shop-test",
            buyer_id="buyer-test",
            conversation_id="conversation-test",
            timestamp=first_clock.now(),
            content="重启恢复测试",
        )
        task = asyncio.create_task(first_service.process(request))
        await asyncio.wait_for(first_clock.wait_until_sleeping(), timeout=0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        second_store = SQLiteReliabilityStore(database_path)
        await second_store.initialize()
        second_service = ReliablePddSimulatorService(
            adapter=adapter,
            repository=InMemoryConversationRepository(),
            store=second_store,
            clock=FakeClock(first_clock.now()),
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=1),
        )
        summary = await second_service.recover_pending()
        transcript = await second_service.transcript(
            ConversationKey(
                shop_id=request.shop_id,
                buyer_id=request.buyer_id,
                conversation_id=request.conversation_id,
            )
        )

        assert summary.scanned == 1
        assert summary.sent == 1
        assert summary.failed == 0
        assert summary.dead_letter == 0
        assert adapter.send_attempt_count == 2
        assert adapter.outbound_count == 1
        assert transcript is not None
        assert [message.direction for message in transcript.messages] == [
            "buyer",
            "service",
        ]

    asyncio.run(scenario())


@pytest.mark.unit
def test_reliable_service_stops_before_adapter_when_database_is_unavailable(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    adapter = MockPddAdapter()
    store = FailOnceClaimStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=InMemoryConversationRepository(),
        store=store,
        clock=clock,
    )
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=clock.now(),
        content="不得进入日志的正文",
    )

    with caplog.at_level(logging.ERROR), pytest.raises(ReliabilityUnavailableError):
        asyncio.run(service.process(request))

    assert adapter.inbound_count == 0
    assert adapter.send_attempt_count == 0
    assert "reliability_database_unavailable" in caplog.messages
    assert request.content not in caplog.text

    result = asyncio.run(service.process(request))

    assert result.processing_status is MessageStatus.SENT
    assert adapter.inbound_count == 1
    assert adapter.outbound_count == 1


@pytest.mark.unit
def test_reliable_service_stops_before_send_when_database_fails_mid_process(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    adapter = MockPddAdapter()
    store = FailOnceInboundMarkStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    repository = InMemoryConversationRepository()
    service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=repository,
        store=store,
        clock=clock,
    )
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=clock.now(),
        content="不得进入日志的中途故障消息",
    )

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ReliabilityUnavailableError),
    ):
        asyncio.run(service.process(request))

    assert adapter.inbound_count == 1
    assert adapter.send_attempt_count == 0
    assert "reliability_database_unavailable" in caplog.messages
    assert request.content not in caplog.text

    summary = asyncio.run(service.recover_pending())
    transcript = asyncio.run(
        service.transcript(
            ConversationKey(
                shop_id=request.shop_id,
                buyer_id=request.buyer_id,
                conversation_id=request.conversation_id,
            )
        )
    )

    assert summary.sent == 1
    assert adapter.inbound_count == 1
    assert adapter.outbound_count == 1
    assert repository.count == 1
    assert transcript is not None
    assert [message.direction for message in transcript.messages] == [
        "buyer",
        "service",
    ]
