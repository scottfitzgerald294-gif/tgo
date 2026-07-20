"""Unit tests for persistent handoff state, queue, audit, and migration."""

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models import (
    ConversationKey,
    ConversationMode,
    HandoffQueueStatus,
    HandoffReason,
    HandoffRiskLevel,
)
from app.repositories import (
    HandoffPersistenceError,
    HandoffTransitionError,
    SQLiteHandoffRepository,
)

SCHEMA_V1_PATH = (
    Path(__file__).parents[2] / "app" / "repositories" / "sql" / "001_reliability.sql"
)
NOW = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
KEY = ConversationKey(
    shop_id="fake-shop",
    buyer_id="fake-buyer",
    conversation_id="fake-conversation",
)


def create_v1_database(database_path: Path) -> None:
    schema = SCHEMA_V1_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(database_path) as connection:
        connection.executescript(schema)
        cursor = connection.execute(
            """
            INSERT INTO inbox_messages (
                shop_id,
                message_id,
                buyer_id,
                conversation_id,
                occurred_at,
                content,
                received_at,
                trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "fake-shop",
                "fake-message",
                "fake-buyer",
                "fake-conversation",
                NOW.isoformat(),
                "FAKE preserved message",
                NOW.isoformat(),
                "00000000-0000-0000-0000-000000000001",
            ),
        )
        inbox_id = cursor.lastrowid
        assert inbox_id is not None
        connection.execute(
            """
            INSERT INTO outbox_messages (
                reply_id,
                inbox_id,
                reply_timestamp,
                content,
                status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "00000000-0000-0000-0000-000000000002",
                inbox_id,
                NOW.isoformat(),
                "FAKE preserved reply",
                "pending",
            ),
        )


@pytest.mark.unit
def test_handoff_repository_migrates_v1_without_losing_reliability_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "connector.sqlite3"
    create_v1_database(database_path)
    repository = SQLiteHandoffRepository(database_path)

    asyncio.run(repository.initialize())

    with sqlite3.connect(database_path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        inbox_count = int(
            connection.execute("SELECT COUNT(*) FROM inbox_messages").fetchone()[0]
        )
        outbox_count = int(
            connection.execute("SELECT COUNT(*) FROM outbox_messages").fetchone()[0]
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

    assert version == 2
    assert inbox_count == 1
    assert outbox_count == 1
    assert {
        "conversation_handoff_states",
        "handoff_queue",
        "handoff_audit_events",
    } <= tables


@pytest.mark.unit
def test_handoff_repository_preserves_unknown_schema_for_diagnosis(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "private-database.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 99")
    repository = SQLiteHandoffRepository(database_path)

    with pytest.raises(HandoffPersistenceError) as captured:
        asyncio.run(repository.initialize())

    with sqlite3.connect(database_path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    assert version == 99
    assert str(database_path) not in str(captured.value)


def lease(database_path: Path) -> tuple[str, int] | None:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT owner, epoch
            FROM reply_leases
            WHERE shop_id = ? AND buyer_id = ? AND conversation_id = ?
            """,
            (KEY.shop_id, KEY.buyer_id, KEY.conversation_id),
        ).fetchone()
    if row is None:
        return None
    return (str(row[0]), int(row[1]))


@pytest.mark.unit
def test_handoff_repository_transitions_ai_waiting_human_and_back_atomically(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "connector.sqlite3"
    repository = SQLiteHandoffRepository(database_path)
    asyncio.run(repository.initialize())

    assert asyncio.run(repository.state(KEY)) is None
    ai_state = asyncio.run(repository.ensure_ai(KEY, occurred_at=NOW))
    waiting_state = asyncio.run(
        repository.request_handoff(
            KEY,
            reason=HandoffReason.REFUND_COMPENSATION_PRICE,
            risk_level=HandoffRiskLevel.HIGH,
            operator="test-router",
            occurred_at=NOW,
        )
    )
    repeated_state = asyncio.run(
        repository.request_handoff(
            KEY,
            reason=HandoffReason.REFUND_COMPENSATION_PRICE,
            risk_level=HandoffRiskLevel.HIGH,
            operator="test-router",
            occurred_at=NOW,
        )
    )
    claimed_state = asyncio.run(
        repository.claim(
            KEY,
            operator="fake-staff",
            occurred_at=NOW,
        )
    )
    before_rejected_resume = (
        asyncio.run(repository.state(KEY)),
        asyncio.run(repository.queue()),
        asyncio.run(repository.audit_for(KEY)),
        lease(database_path),
    )
    with pytest.raises(HandoffTransitionError):
        asyncio.run(
            repository.resume_ai(
                KEY,
                operator="fake-staff",
                risk_acknowledged=False,
                occurred_at=NOW,
            )
        )
    assert (
        asyncio.run(repository.state(KEY)),
        asyncio.run(repository.queue()),
        asyncio.run(repository.audit_for(KEY)),
        lease(database_path),
    ) == before_rejected_resume

    resumed_state = asyncio.run(
        repository.resume_ai(
            KEY,
            operator="fake-staff",
            risk_acknowledged=True,
            occurred_at=NOW,
        )
    )
    queue = asyncio.run(repository.queue())
    audit = asyncio.run(repository.audit_for(KEY))

    assert ai_state.mode is ConversationMode.AI
    assert waiting_state.mode is ConversationMode.WAITING_HUMAN
    assert repeated_state == waiting_state
    assert claimed_state.mode is ConversationMode.HUMAN
    assert resumed_state.mode is ConversationMode.AI
    assert len(queue) == 0
    assert lease(database_path) == ("ai", 2)
    assert [event.event for event in audit] == [
        "conversation_initialized",
        "handoff_requested",
        "handoff_claimed",
        "ai_resumed",
    ]
    assert all("content" not in event.model_dump() for event in audit)


@pytest.mark.unit
def test_handoff_repository_enforces_queue_and_closed_terminal_state(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "connector.sqlite3"
    repository = SQLiteHandoffRepository(database_path)
    asyncio.run(repository.initialize())
    asyncio.run(
        repository.request_handoff(
            KEY,
            reason=HandoffReason.PRODUCT_SAFETY_INJURY,
            risk_level=HandoffRiskLevel.CRITICAL,
            operator="test-router",
            occurred_at=NOW,
        )
    )
    open_queue = asyncio.run(repository.queue())

    assert len(open_queue) == 1
    assert open_queue[0].status is HandoffQueueStatus.WAITING
    assert lease(database_path) == ("human", 1)

    closed_state = asyncio.run(
        repository.close(
            KEY,
            operator="fake-staff",
            occurred_at=NOW,
        )
    )
    before_rejected = (
        closed_state,
        asyncio.run(repository.queue()),
        asyncio.run(repository.audit_for(KEY)),
        lease(database_path),
    )

    with pytest.raises(HandoffTransitionError):
        asyncio.run(
            repository.resume_ai(
                KEY,
                operator="fake-staff",
                risk_acknowledged=True,
                occurred_at=NOW,
            )
        )
    with pytest.raises(HandoffTransitionError):
        asyncio.run(
            repository.request_handoff(
                KEY,
                reason=HandoffReason.HUMAN_REQUESTED,
                risk_level=HandoffRiskLevel.MEDIUM,
                operator="test-router",
                occurred_at=NOW,
            )
        )

    assert (
        asyncio.run(repository.state(KEY)),
        asyncio.run(repository.queue()),
        asyncio.run(repository.audit_for(KEY)),
        lease(database_path),
    ) == before_rejected
    assert closed_state.mode is ConversationMode.CLOSED
    assert asyncio.run(repository.queue()) == ()
    assert lease(database_path) == ("human", 2)


@pytest.mark.unit
def test_handoff_repository_rejects_direct_claim_and_unsafe_operator(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "connector.sqlite3"
    repository = SQLiteHandoffRepository(database_path)
    asyncio.run(repository.initialize())
    asyncio.run(repository.ensure_ai(KEY, occurred_at=NOW))
    before = (
        asyncio.run(repository.state(KEY)),
        asyncio.run(repository.queue()),
        asyncio.run(repository.audit_for(KEY)),
        lease(database_path),
    )

    with pytest.raises(HandoffTransitionError):
        asyncio.run(
            repository.claim(
                KEY,
                operator="fake-staff",
                occurred_at=NOW,
            )
        )
    with pytest.raises(HandoffTransitionError):
        asyncio.run(
            repository.request_handoff(
                KEY,
                reason=HandoffReason.HUMAN_REQUESTED,
                risk_level=HandoffRiskLevel.MEDIUM,
                operator="real-operator",
                occurred_at=NOW,
            )
        )

    assert (
        asyncio.run(repository.state(KEY)),
        asyncio.run(repository.queue()),
        asyncio.run(repository.audit_for(KEY)),
        lease(database_path),
    ) == before
