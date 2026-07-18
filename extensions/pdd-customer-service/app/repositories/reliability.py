"""SQLite-backed Inbox, Outbox, lease, and audit persistence."""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from app.models import (
    AuditRecord,
    ClaimResult,
    ConversationKey,
    ConversationMessage,
    ConversationTranscript,
    MessageKey,
    MessageStatus,
    PddTextMessageRequest,
    ReliabilityRecord,
    ReplyOwner,
)

SCHEMA_VERSION = 1
SCHEMA_PATH = Path(__file__).with_name("sql") / "001_reliability.sql"


class PersistenceUnavailableError(RuntimeError):
    """Raised when the local durable ledger cannot complete an operation."""


class ReliabilityStore(Protocol):
    """Persistence boundary required by durable message orchestration."""

    async def initialize(self) -> None: ...

    async def claim(
        self,
        request: PddTextMessageRequest,
        *,
        received_at: datetime,
        trace_id: UUID,
        reply_id: UUID,
        reply_timestamp: datetime,
        reply_content: str,
    ) -> ClaimResult: ...

    async def mark_inbound_recorded(
        self,
        inbox_id: int,
        *,
        recorded_at: datetime,
    ) -> ReliabilityRecord: ...

    async def mark_conversation_created(
        self,
        inbox_id: int,
        *,
        conversation_created: bool,
        recorded_at: datetime,
    ) -> ReliabilityRecord: ...

    async def update_delivery(
        self,
        inbox_id: int,
        *,
        status: MessageStatus,
        attempts: int,
        retryable: bool,
        reason: str | None,
        next_attempt_at: datetime | None,
        lease_epoch: int | None,
        event: str,
        recorded_at: datetime,
    ) -> ReliabilityRecord: ...

    async def audit_for(self, inbox_id: int) -> tuple[AuditRecord, ...]: ...

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None: ...

    async def acquire_ai_lease(
        self,
        key: ConversationKey,
        *,
        recorded_at: datetime,
    ) -> int | None: ...

    async def lease_is_current(
        self,
        key: ConversationKey,
        *,
        owner: ReplyOwner,
        epoch: int,
    ) -> bool: ...

    async def take_human_ownership(
        self,
        key: ConversationKey,
        *,
        recorded_at: datetime,
    ) -> int: ...

    async def release_to_ai(
        self,
        key: ConversationKey,
        *,
        recorded_at: datetime,
    ) -> int: ...

    async def recoverable(
        self,
        *,
        now: datetime,
    ) -> tuple[ReliabilityRecord, ...]: ...


class SQLiteReliabilityStore:
    """Own the extension-local SQLite reliability ledger."""

    def __init__(
        self,
        database_path: Path,
        *,
        timeout_seconds: float = 0.2,
    ) -> None:
        self._database_path = database_path
        self._timeout_seconds = timeout_seconds

    async def initialize(self) -> None:
        """Create or validate the versioned schema without import side effects."""
        try:
            await asyncio.to_thread(self._initialize_sync)
        except sqlite3.OperationalError as error:
            raise self._unavailable("initialize") from error

    async def claim(
        self,
        request: PddTextMessageRequest,
        *,
        received_at: datetime,
        trace_id: UUID,
        reply_id: UUID,
        reply_timestamp: datetime,
        reply_content: str,
    ) -> ClaimResult:
        """Atomically create one Inbox/Outbox pair or return the existing pair."""
        try:
            return await asyncio.to_thread(
                self._claim_sync,
                request,
                received_at,
                trace_id,
                reply_id,
                reply_timestamp,
                reply_content,
            )
        except sqlite3.OperationalError as error:
            raise self._unavailable("claim") from error

    async def mark_inbound_recorded(
        self,
        inbox_id: int,
        *,
        recorded_at: datetime,
    ) -> ReliabilityRecord:
        """Persist that the synthetic inbound adapter accepted the message."""
        try:
            return await asyncio.to_thread(
                self._mark_inbound_recorded_sync,
                inbox_id,
                recorded_at,
            )
        except sqlite3.OperationalError as error:
            raise self._unavailable("mark inbound") from error

    async def mark_conversation_created(
        self,
        inbox_id: int,
        *,
        conversation_created: bool,
        recorded_at: datetime,
    ) -> ReliabilityRecord:
        """Persist the original conversation-association result."""
        try:
            return await asyncio.to_thread(
                self._mark_conversation_created_sync,
                inbox_id,
                conversation_created,
                recorded_at,
            )
        except sqlite3.OperationalError as error:
            raise self._unavailable("mark conversation") from error

    async def update_delivery(
        self,
        inbox_id: int,
        *,
        status: MessageStatus,
        attempts: int,
        retryable: bool,
        reason: str | None,
        next_attempt_at: datetime | None,
        lease_epoch: int | None,
        event: str,
        recorded_at: datetime,
    ) -> ReliabilityRecord:
        """Atomically update Outbox delivery state and append its audit."""
        try:
            return await asyncio.to_thread(
                self._update_delivery_sync,
                inbox_id,
                status,
                attempts,
                retryable,
                reason,
                next_attempt_at,
                lease_epoch,
                event,
                recorded_at,
            )
        except sqlite3.OperationalError as error:
            raise self._unavailable("update delivery") from error

    async def audit_for(self, inbox_id: int) -> tuple[AuditRecord, ...]:
        """Return body-free audit entries in append order."""
        try:
            return await asyncio.to_thread(self._audit_for_sync, inbox_id)
        except sqlite3.OperationalError as error:
            raise self._unavailable("read audit") from error

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None:
        """Rebuild a buyer-visible transcript from the durable ledger."""
        try:
            return await asyncio.to_thread(self._transcript_sync, key)
        except sqlite3.OperationalError as error:
            raise self._unavailable("read transcript") from error

    async def acquire_ai_lease(
        self,
        key: ConversationKey,
        *,
        recorded_at: datetime,
    ) -> int | None:
        """Return the current AI epoch unless a human owns the conversation."""
        try:
            return await asyncio.to_thread(
                self._acquire_ai_lease_sync,
                key,
                recorded_at,
            )
        except sqlite3.OperationalError as error:
            raise self._unavailable("acquire ai lease") from error

    async def lease_is_current(
        self,
        key: ConversationKey,
        *,
        owner: ReplyOwner,
        epoch: int,
    ) -> bool:
        """Check owner and epoch immediately before an outbound send."""
        try:
            return await asyncio.to_thread(
                self._lease_is_current_sync,
                key,
                owner,
                epoch,
            )
        except sqlite3.OperationalError as error:
            raise self._unavailable("check reply lease") from error

    async def take_human_ownership(
        self,
        key: ConversationKey,
        *,
        recorded_at: datetime,
    ) -> int:
        """Move a conversation to human ownership and advance its epoch."""
        try:
            return await asyncio.to_thread(
                self._set_lease_owner_sync,
                key,
                ReplyOwner.HUMAN,
                recorded_at,
            )
        except sqlite3.OperationalError as error:
            raise self._unavailable("take human ownership") from error

    async def release_to_ai(
        self,
        key: ConversationKey,
        *,
        recorded_at: datetime,
    ) -> int:
        """Explicitly return a conversation to AI and advance its epoch."""
        try:
            return await asyncio.to_thread(
                self._set_lease_owner_sync,
                key,
                ReplyOwner.AI,
                recorded_at,
            )
        except sqlite3.OperationalError as error:
            raise self._unavailable("release to ai") from error

    async def recoverable(
        self,
        *,
        now: datetime,
    ) -> tuple[ReliabilityRecord, ...]:
        """Return due retryable records that are incomplete."""
        try:
            return await asyncio.to_thread(self._recoverable_sync, now)
        except sqlite3.OperationalError as error:
            raise self._unavailable("scan recovery") from error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            timeout=self._timeout_seconds,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_sync(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                connection.executescript(schema)
            elif version != SCHEMA_VERSION:
                raise RuntimeError("Unsupported reliability schema version")

    def _claim_sync(
        self,
        request: PddTextMessageRequest,
        received_at: datetime,
        trace_id: UUID,
        reply_id: UUID,
        reply_timestamp: datetime,
        reply_content: str,
    ) -> ClaimResult:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO inbox_messages (
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
                    request.shop_id,
                    request.message_id,
                    request.buyer_id,
                    request.conversation_id,
                    request.timestamp.isoformat(),
                    request.content,
                    received_at.isoformat(),
                    str(trace_id),
                ),
            )
            is_new = cursor.rowcount == 1
            if is_new:
                lastrowid = cursor.lastrowid
                if lastrowid is None:
                    raise RuntimeError("Claim insert did not return an Inbox id")
                inbox_id = int(lastrowid)
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
                        str(reply_id),
                        inbox_id,
                        reply_timestamp.isoformat(),
                        reply_content,
                        MessageStatus.PENDING.value,
                    ),
                )
                self._insert_audit(
                    connection,
                    inbox_id=inbox_id,
                    trace_id=trace_id,
                    event="message_claimed",
                    status=MessageStatus.PENDING,
                    attempt=0,
                    reason=None,
                    created_at=received_at,
                )
            else:
                existing = connection.execute(
                    """
                    SELECT inbox_id, trace_id
                    FROM inbox_messages
                    WHERE shop_id = ? AND message_id = ?
                    """,
                    (request.shop_id, request.message_id),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("Claim conflict record is missing")
                inbox_id = int(existing["inbox_id"])
                existing_outbox = connection.execute(
                    """
                    SELECT status, attempts
                    FROM outbox_messages
                    WHERE inbox_id = ?
                    """,
                    (inbox_id,),
                ).fetchone()
                if existing_outbox is None:
                    raise RuntimeError("Claim conflict outbox is missing")
                self._insert_audit(
                    connection,
                    inbox_id=inbox_id,
                    trace_id=UUID(str(existing["trace_id"])),
                    event="duplicate_detected",
                    status=MessageStatus(str(existing_outbox["status"])),
                    attempt=int(existing_outbox["attempts"]),
                    reason="duplicate_message_key",
                    created_at=received_at,
                )

            row = self._select_record(connection, inbox_id)
            connection.commit()
            return ClaimResult(record=self._record_from_row(row), is_new=is_new)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _mark_inbound_recorded_sync(
        self,
        inbox_id: int,
        recorded_at: datetime,
    ) -> ReliabilityRecord:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE inbox_messages
                SET inbound_recorded = 1
                WHERE inbox_id = ?
                """,
                (inbox_id,),
            )
            row = self._select_record(connection, inbox_id)
            self._insert_audit(
                connection,
                inbox_id=inbox_id,
                trace_id=UUID(str(row["trace_id"])),
                event="inbound_recorded",
                status=MessageStatus(str(row["status"])),
                attempt=int(row["attempts"]),
                reason=None,
                created_at=recorded_at,
            )
            connection.commit()
            return self._record_from_row(row)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _mark_conversation_created_sync(
        self,
        inbox_id: int,
        conversation_created: bool,
        recorded_at: datetime,
    ) -> ReliabilityRecord:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE inbox_messages
                SET conversation_created = ?
                WHERE inbox_id = ?
                """,
                (int(conversation_created), inbox_id),
            )
            row = self._select_record(connection, inbox_id)
            self._insert_audit(
                connection,
                inbox_id=inbox_id,
                trace_id=UUID(str(row["trace_id"])),
                event="conversation_associated",
                status=MessageStatus(str(row["status"])),
                attempt=int(row["attempts"]),
                reason=None,
                created_at=recorded_at,
            )
            connection.commit()
            return self._record_from_row(row)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _update_delivery_sync(
        self,
        inbox_id: int,
        status: MessageStatus,
        attempts: int,
        retryable: bool,
        reason: str | None,
        next_attempt_at: datetime | None,
        lease_epoch: int | None,
        event: str,
        recorded_at: datetime,
    ) -> ReliabilityRecord:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE outbox_messages
                SET
                    status = ?,
                    attempts = ?,
                    retryable = ?,
                    last_reason = ?,
                    next_attempt_at = ?,
                    lease_epoch = ?
                WHERE inbox_id = ?
                """,
                (
                    status.value,
                    attempts,
                    int(retryable),
                    reason,
                    (
                        next_attempt_at.isoformat()
                        if next_attempt_at is not None
                        else None
                    ),
                    lease_epoch,
                    inbox_id,
                ),
            )
            row = self._select_record(connection, inbox_id)
            self._insert_audit(
                connection,
                inbox_id=inbox_id,
                trace_id=UUID(str(row["trace_id"])),
                event=event,
                status=status,
                attempt=attempts,
                reason=reason,
                created_at=recorded_at,
            )
            connection.commit()
            return self._record_from_row(row)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _audit_for_sync(self, inbox_id: int) -> tuple[AuditRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    audit_id,
                    trace_id,
                    event,
                    status,
                    attempt,
                    reason,
                    created_at
                FROM audit_events
                WHERE inbox_id = ?
                ORDER BY audit_id
                """,
                (inbox_id,),
            ).fetchall()
        return tuple(
            AuditRecord(
                audit_id=int(row["audit_id"]),
                trace_id=UUID(str(row["trace_id"])),
                event=str(row["event"]),
                status=(
                    MessageStatus(str(row["status"]))
                    if row["status"] is not None
                    else None
                ),
                attempt=int(row["attempt"]),
                reason=str(row["reason"]) if row["reason"] is not None else None,
                created_at=datetime.fromisoformat(str(row["created_at"])),
            )
            for row in rows
        )

    def _transcript_sync(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    i.message_id,
                    i.occurred_at,
                    i.content AS inbound_content,
                    i.inbound_recorded,
                    o.reply_id,
                    o.reply_timestamp,
                    o.content AS reply_content,
                    o.status
                FROM inbox_messages AS i
                JOIN outbox_messages AS o ON o.inbox_id = i.inbox_id
                WHERE
                    i.shop_id = ?
                    AND i.buyer_id = ?
                    AND i.conversation_id = ?
                ORDER BY i.inbox_id
                """,
                (key.shop_id, key.buyer_id, key.conversation_id),
            ).fetchall()
        messages: list[ConversationMessage] = []
        for row in rows:
            if bool(row["inbound_recorded"]):
                messages.append(
                    ConversationMessage(
                        direction="buyer",
                        message_id=str(row["message_id"]),
                        timestamp=datetime.fromisoformat(str(row["occurred_at"])),
                        content=str(row["inbound_content"]),
                    )
                )
            if MessageStatus(str(row["status"])) is MessageStatus.SENT:
                messages.append(
                    ConversationMessage(
                        direction="service",
                        message_id=str(row["reply_id"]),
                        timestamp=datetime.fromisoformat(str(row["reply_timestamp"])),
                        content=str(row["reply_content"]),
                    )
                )
        if not messages:
            return None
        return ConversationTranscript(key=key, messages=tuple(messages))

    def _acquire_ai_lease_sync(
        self,
        key: ConversationKey,
        recorded_at: datetime,
    ) -> int | None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select_lease(connection, key)
            if row is None:
                epoch = 1
                connection.execute(
                    """
                    INSERT INTO reply_leases (
                        shop_id,
                        buyer_id,
                        conversation_id,
                        owner,
                        epoch,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key.shop_id,
                        key.buyer_id,
                        key.conversation_id,
                        ReplyOwner.AI.value,
                        epoch,
                        recorded_at.isoformat(),
                    ),
                )
            elif ReplyOwner(str(row["owner"])) is ReplyOwner.HUMAN:
                connection.commit()
                return None
            else:
                epoch = int(row["epoch"])
            connection.commit()
            return epoch
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _lease_is_current_sync(
        self,
        key: ConversationKey,
        owner: ReplyOwner,
        epoch: int,
    ) -> bool:
        with self._connect() as connection:
            row = self._select_lease(connection, key)
        return (
            row is not None
            and ReplyOwner(str(row["owner"])) is owner
            and int(row["epoch"]) == epoch
        )

    def _set_lease_owner_sync(
        self,
        key: ConversationKey,
        owner: ReplyOwner,
        recorded_at: datetime,
    ) -> int:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select_lease(connection, key)
            epoch = 1 if row is None else int(row["epoch"]) + 1
            connection.execute(
                """
                INSERT INTO reply_leases (
                    shop_id,
                    buyer_id,
                    conversation_id,
                    owner,
                    epoch,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (shop_id, buyer_id, conversation_id)
                DO UPDATE SET
                    owner = excluded.owner,
                    epoch = excluded.epoch,
                    updated_at = excluded.updated_at
                """,
                (
                    key.shop_id,
                    key.buyer_id,
                    key.conversation_id,
                    owner.value,
                    epoch,
                    recorded_at.isoformat(),
                ),
            )
            connection.commit()
            return epoch
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _select_lease(
        connection: sqlite3.Connection,
        key: ConversationKey,
    ) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            connection.execute(
                """
                SELECT owner, epoch
                FROM reply_leases
                WHERE
                    shop_id = ?
                    AND buyer_id = ?
                    AND conversation_id = ?
                """,
                (key.shop_id, key.buyer_id, key.conversation_id),
            ).fetchone(),
        )

    def _recoverable_sync(
        self,
        now: datetime,
    ) -> tuple[ReliabilityRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT i.inbox_id
                FROM inbox_messages AS i
                JOIN outbox_messages AS o ON o.inbox_id = i.inbox_id
                WHERE
                    o.status IN ('pending', 'failed', 'retrying')
                    AND o.retryable = 1
                    AND (
                        o.next_attempt_at IS NULL
                        OR o.next_attempt_at <= ?
                    )
                ORDER BY i.inbox_id
                """,
                (now.isoformat(),),
            ).fetchall()
            return tuple(
                self._record_from_row(
                    self._select_record(connection, int(row["inbox_id"]))
                )
                for row in rows
            )

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        *,
        inbox_id: int,
        trace_id: UUID,
        event: str,
        status: MessageStatus | None,
        attempt: int,
        reason: str | None,
        created_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events (
                inbox_id,
                trace_id,
                event,
                status,
                attempt,
                reason,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inbox_id,
                str(trace_id),
                event,
                status.value if status is not None else None,
                attempt,
                reason,
                created_at.isoformat(),
            ),
        )

    @staticmethod
    def _select_record(
        connection: sqlite3.Connection,
        inbox_id: int,
    ) -> sqlite3.Row:
        row = cast(
            sqlite3.Row | None,
            connection.execute(
                """
                SELECT
                    i.inbox_id,
                    i.shop_id,
                    i.message_id,
                    i.buyer_id,
                    i.conversation_id,
                    i.occurred_at,
                    i.content AS inbound_content,
                    i.received_at,
                    i.trace_id,
                    i.inbound_recorded,
                    i.conversation_created,
                    o.reply_id,
                    o.reply_timestamp,
                    o.content AS reply_content,
                    o.status,
                    o.attempts,
                    o.retryable,
                    o.last_reason,
                    o.next_attempt_at,
                    o.lease_epoch
                FROM inbox_messages AS i
                JOIN outbox_messages AS o ON o.inbox_id = i.inbox_id
                WHERE i.inbox_id = ?
                """,
                (inbox_id,),
            ).fetchone(),
        )
        if row is None:
            raise RuntimeError("Reliability record is missing")
        return row

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ReliabilityRecord:
        next_attempt = row["next_attempt_at"]
        lease_epoch = row["lease_epoch"]
        return ReliabilityRecord(
            inbox_id=int(row["inbox_id"]),
            key=MessageKey(
                shop_id=str(row["shop_id"]),
                message_id=str(row["message_id"]),
            ),
            conversation_key=ConversationKey(
                shop_id=str(row["shop_id"]),
                buyer_id=str(row["buyer_id"]),
                conversation_id=str(row["conversation_id"]),
            ),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            content=str(row["inbound_content"]),
            received_at=datetime.fromisoformat(str(row["received_at"])),
            trace_id=UUID(str(row["trace_id"])),
            reply_id=UUID(str(row["reply_id"])),
            reply_timestamp=datetime.fromisoformat(str(row["reply_timestamp"])),
            reply_content=str(row["reply_content"]),
            status=MessageStatus(str(row["status"])),
            attempts=int(row["attempts"]),
            retryable=bool(row["retryable"]),
            last_reason=(
                str(row["last_reason"]) if row["last_reason"] is not None else None
            ),
            next_attempt_at=(
                datetime.fromisoformat(str(next_attempt))
                if next_attempt is not None
                else None
            ),
            lease_epoch=int(lease_epoch) if lease_epoch is not None else None,
            inbound_recorded=bool(row["inbound_recorded"]),
            conversation_created=bool(row["conversation_created"]),
        )

    @staticmethod
    def _unavailable(operation: str) -> PersistenceUnavailableError:
        return PersistenceUnavailableError(
            f"Reliability persistence unavailable during {operation}"
        )
