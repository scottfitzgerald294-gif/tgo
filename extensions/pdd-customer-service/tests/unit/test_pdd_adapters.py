"""Unit tests for local PDD adapters."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.adapters.pdd import MockPddAdapter
from app.models import ConversationKey, NormalizedMessage, OutboundMessage


def build_message() -> NormalizedMessage:
    now = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
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
