"""Unit tests for typed simulator message models."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import (
    ConversationKey,
    NormalizedMessage,
    OutboundMessage,
    PddTextMessageRequest,
)


@pytest.mark.unit
def test_simulated_text_request_normalizes_identifiers() -> None:
    request = PddTextMessageRequest(
        message_id=" message-001 ",
        shop_id=" shop-test ",
        buyer_id=" buyer-test ",
        conversation_id=" conversation-test ",
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
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
            timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
            content=content,
        )


@pytest.mark.unit
@pytest.mark.parametrize("message_id", ["", " " * 4, "m" * 129])
def test_simulated_text_request_rejects_invalid_identifier(
    message_id: str,
) -> None:
    with pytest.raises(ValidationError):
        PddTextMessageRequest(
            message_id=message_id,
            shop_id="shop-test",
            buyer_id="buyer-test",
            conversation_id="conversation-test",
            timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
            content="你好",
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


@pytest.mark.unit
def test_normalized_and_outbound_messages_share_trace_context() -> None:
    now = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
    trace_id = uuid4()
    normalized = NormalizedMessage(
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
        shop_id=normalized.shop_id,
        buyer_id=normalized.buyer_id,
        conversation_id=normalized.conversation_id,
        in_reply_to_message_id=normalized.message_id,
        timestamp=now,
        content="已收到测试消息",
    )

    assert normalized.source == "mock-pdd"
    assert outbound.trace_id == normalized.trace_id
    assert outbound.in_reply_to_message_id == normalized.message_id
