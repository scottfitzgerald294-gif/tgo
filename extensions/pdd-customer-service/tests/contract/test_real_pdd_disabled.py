"""Contract guard that keeps the real PDD adapter disabled."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.adapters.pdd import RealPddAdapter, RealPddNotConfiguredError
from app.models import ConversationKey, NormalizedMessage, OutboundMessage


@pytest.mark.contract
def test_real_pdd_adapter_cannot_be_used_without_official_contract() -> None:
    adapter = RealPddAdapter()
    now = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
    trace_id = uuid4()
    inbound = NormalizedMessage(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=now,
        content="你好",
        received_at=now,
        trace_id=trace_id,
    )
    outbound = OutboundMessage(
        reply_id=uuid4(),
        trace_id=trace_id,
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        in_reply_to_message_id="message-001",
        timestamp=now,
        content="已收到测试消息",
    )
    key = ConversationKey(
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
    )

    with pytest.raises(RealPddNotConfiguredError):
        asyncio.run(adapter.receive(inbound))
    with pytest.raises(RealPddNotConfiguredError):
        asyncio.run(adapter.send(outbound))
    with pytest.raises(RealPddNotConfiguredError):
        asyncio.run(adapter.transcript(key))
