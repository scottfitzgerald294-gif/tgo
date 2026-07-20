"""Unit tests for simulator message orchestration."""

import asyncio
import logging
from datetime import UTC, datetime

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
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
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
    assert all(
        getattr(record, "message_id", None) == request.message_id
        for record in caplog.records
    )
    assert all(
        getattr(record, "conversation_id", None) == request.conversation_id
        for record in caplog.records
    )
    assert [getattr(record, "direction", None) for record in caplog.records] == [
        "inbound",
        "outbound",
    ]
    assert all(not hasattr(record, "content") for record in caplog.records)


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
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
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
