"""Unit tests for the durable SQLite reliability ledger."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.models import MessageStatus, PddTextMessageRequest, ReplyOwner
from app.repositories import SQLiteReliabilityStore


@pytest.mark.unit
def test_store_claims_message_once(tmp_path: Path) -> None:
    store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        content="你好",
    )
    received_at = datetime(2026, 7, 18, 9, 0, 1, tzinfo=UTC)

    first = asyncio.run(
        store.claim(
            request,
            received_at=received_at,
            trace_id=uuid4(),
            reply_id=uuid4(),
            reply_timestamp=received_at,
            reply_content="已收到测试消息",
        )
    )
    second = asyncio.run(
        store.claim(
            request,
            received_at=received_at,
            trace_id=uuid4(),
            reply_id=uuid4(),
            reply_timestamp=received_at,
            reply_content="不应覆盖既有回复",
        )
    )

    assert first.is_new is True
    assert second.is_new is False
    assert second.record.inbox_id == first.record.inbox_id
    assert second.record.trace_id == first.record.trace_id
    assert second.record.reply_id == first.record.reply_id
    assert second.record.reply_content == "已收到测试消息"


@pytest.mark.unit
def test_store_persists_delivery_audit_and_transcript_across_reopen(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "reliability.sqlite3"
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        content="你好",
    )
    received_at = datetime(2026, 7, 18, 9, 0, 1, tzinfo=UTC)
    store = SQLiteReliabilityStore(database_path)
    asyncio.run(store.initialize())
    claimed = asyncio.run(
        store.claim(
            request,
            received_at=received_at,
            trace_id=uuid4(),
            reply_id=uuid4(),
            reply_timestamp=received_at,
            reply_content="已收到测试消息",
        )
    )
    asyncio.run(
        store.mark_inbound_recorded(
            claimed.record.inbox_id,
            recorded_at=received_at,
        )
    )
    asyncio.run(
        store.mark_conversation_created(
            claimed.record.inbox_id,
            conversation_created=True,
            recorded_at=received_at,
        )
    )
    asyncio.run(
        store.update_delivery(
            claimed.record.inbox_id,
            status=MessageStatus.FAILED,
            attempts=1,
            retryable=True,
            reason="mock_send_error",
            next_attempt_at=None,
            lease_epoch=1,
            event="send_failed",
            recorded_at=received_at,
        )
    )
    asyncio.run(
        store.update_delivery(
            claimed.record.inbox_id,
            status=MessageStatus.RETRYING,
            attempts=1,
            retryable=True,
            reason="mock_send_error",
            next_attempt_at=received_at,
            lease_epoch=1,
            event="retry_scheduled",
            recorded_at=received_at,
        )
    )
    sent = asyncio.run(
        store.update_delivery(
            claimed.record.inbox_id,
            status=MessageStatus.SENT,
            attempts=2,
            retryable=False,
            reason=None,
            next_attempt_at=None,
            lease_epoch=1,
            event="reply_sent",
            recorded_at=received_at,
        )
    )

    reopened = SQLiteReliabilityStore(database_path)
    asyncio.run(reopened.initialize())
    duplicate = asyncio.run(
        reopened.claim(
            request,
            received_at=received_at,
            trace_id=uuid4(),
            reply_id=uuid4(),
            reply_timestamp=received_at,
            reply_content="不应覆盖既有回复",
        )
    )
    transcript = asyncio.run(reopened.transcript(sent.conversation_key))
    audits = asyncio.run(reopened.audit_for(sent.inbox_id))

    assert duplicate.record.status is MessageStatus.SENT
    assert duplicate.record.attempts == 2
    assert duplicate.record.conversation_created is True
    assert transcript is not None
    assert [message.direction for message in transcript.messages] == [
        "buyer",
        "service",
    ]
    assert [message.content for message in transcript.messages] == [
        "你好",
        "已收到测试消息",
    ]
    assert [audit.event for audit in audits] == [
        "message_claimed",
        "inbound_recorded",
        "conversation_associated",
        "send_failed",
        "retry_scheduled",
        "reply_sent",
        "duplicate_detected",
    ]


@pytest.mark.unit
def test_store_enforces_reply_epoch_and_recovers_only_due_retryable_records(
    tmp_path: Path,
) -> None:
    store = SQLiteReliabilityStore(tmp_path / "reliability.sqlite3")
    asyncio.run(store.initialize())
    now = datetime(2026, 7, 18, 9, 0, 1, tzinfo=UTC)
    request = PddTextMessageRequest(
        message_id="message-001",
        shop_id="shop-test",
        buyer_id="buyer-test",
        conversation_id="conversation-test",
        timestamp=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        content="你好",
    )
    first = asyncio.run(
        store.claim(
            request,
            received_at=now,
            trace_id=uuid4(),
            reply_id=uuid4(),
            reply_timestamp=now,
            reply_content="已收到测试消息",
        )
    )
    second = asyncio.run(
        store.claim(
            request.model_copy(update={"message_id": "message-002"}),
            received_at=now,
            trace_id=uuid4(),
            reply_id=uuid4(),
            reply_timestamp=now,
            reply_content="已收到测试消息",
        )
    )

    ai_epoch = asyncio.run(
        store.acquire_ai_lease(first.record.conversation_key, recorded_at=now)
    )
    assert ai_epoch == 1
    assert (
        asyncio.run(
            store.lease_is_current(
                first.record.conversation_key,
                owner=ReplyOwner.AI,
                epoch=ai_epoch,
            )
        )
        is True
    )
    human_epoch = asyncio.run(
        store.take_human_ownership(first.record.conversation_key, recorded_at=now)
    )
    assert human_epoch == 2
    assert (
        asyncio.run(
            store.lease_is_current(
                first.record.conversation_key,
                owner=ReplyOwner.AI,
                epoch=ai_epoch,
            )
        )
        is False
    )
    assert (
        asyncio.run(
            store.acquire_ai_lease(first.record.conversation_key, recorded_at=now)
        )
        is None
    )
    released_epoch = asyncio.run(
        store.release_to_ai(first.record.conversation_key, recorded_at=now)
    )
    assert released_epoch == 3

    asyncio.run(
        store.update_delivery(
            first.record.inbox_id,
            status=MessageStatus.RETRYING,
            attempts=1,
            retryable=True,
            reason="mock_send_error",
            next_attempt_at=now,
            lease_epoch=released_epoch,
            event="retry_scheduled",
            recorded_at=now,
        )
    )
    asyncio.run(
        store.update_delivery(
            second.record.inbox_id,
            status=MessageStatus.RETRYING,
            attempts=1,
            retryable=True,
            reason="mock_send_error",
            next_attempt_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC),
            lease_epoch=released_epoch,
            event="retry_scheduled",
            recorded_at=now,
        )
    )

    recoverable = asyncio.run(store.recoverable(now=now))

    assert [record.inbox_id for record in recoverable] == [first.record.inbox_id]
