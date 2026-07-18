"""SQLite persistence boundary for deterministic human handoff."""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from app.models import (
    ConversationHandoffState,
    ConversationKey,
    ConversationMode,
    HandoffAuditEvent,
    HandoffQueueItem,
    HandoffQueueStatus,
    HandoffReason,
    HandoffRiskLevel,
    ReplyOwner,
)

SCHEMA_VERSION = 2
SCHEMA_DIRECTORY = Path(__file__).with_name("sql")
SCHEMA_V1_PATH = SCHEMA_DIRECTORY / "001_reliability.sql"
SCHEMA_V2_PATH = SCHEMA_DIRECTORY / "002_handoff.sql"


class HandoffPersistenceError(RuntimeError):
    """Raised when persistent handoff state is unavailable."""


class HandoffTransitionError(ValueError):
    """Raised when a requested state transition is not allowed."""


class HandoffNotFoundError(LookupError):
    """Raised when a state-changing operation targets no conversation."""


class HandoffRepository(Protocol):
    """Persistent state boundary required by handoff orchestration."""

    async def initialize(self) -> None: ...

    async def state(
        self,
        key: ConversationKey,
    ) -> ConversationHandoffState | None: ...

    async def ensure_ai(
        self,
        key: ConversationKey,
        *,
        occurred_at: datetime,
    ) -> ConversationHandoffState: ...

    async def request_handoff(
        self,
        key: ConversationKey,
        *,
        reason: HandoffReason,
        risk_level: HandoffRiskLevel,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState: ...

    async def claim(
        self,
        key: ConversationKey,
        *,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState: ...

    async def resume_ai(
        self,
        key: ConversationKey,
        *,
        operator: str,
        risk_acknowledged: bool,
        occurred_at: datetime,
    ) -> ConversationHandoffState: ...

    async def close(
        self,
        key: ConversationKey,
        *,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState: ...

    async def queue(self) -> tuple[HandoffQueueItem, ...]: ...

    async def audit_for(
        self,
        key: ConversationKey,
    ) -> tuple[HandoffAuditEvent, ...]: ...


class SQLiteHandoffRepository:
    """Persist handoff state beside the existing reliability ledger."""

    def __init__(
        self,
        database_path: Path,
        *,
        timeout_seconds: float = 0.2,
    ) -> None:
        self._database_path = database_path
        self._timeout_seconds = timeout_seconds

    async def initialize(self) -> None:
        """Migrate schema v1 to v2 without deleting reliability data."""

        try:
            await asyncio.to_thread(self._initialize_sync)
        except (OSError, sqlite3.Error, RuntimeError) as error:
            raise HandoffPersistenceError(
                "Handoff persistence unavailable during initialize"
            ) from error

    async def state(
        self,
        key: ConversationKey,
    ) -> ConversationHandoffState | None:
        try:
            return await asyncio.to_thread(self._state_sync, key)
        except (OSError, sqlite3.Error) as error:
            raise self._unavailable("read state") from error

    async def ensure_ai(
        self,
        key: ConversationKey,
        *,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        try:
            return await asyncio.to_thread(
                self._ensure_ai_sync,
                key,
                occurred_at,
            )
        except (OSError, sqlite3.Error) as error:
            raise self._unavailable("initialize conversation") from error

    async def request_handoff(
        self,
        key: ConversationKey,
        *,
        reason: HandoffReason,
        risk_level: HandoffRiskLevel,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        try:
            return await asyncio.to_thread(
                self._request_handoff_sync,
                key,
                reason,
                risk_level,
                operator,
                occurred_at,
            )
        except (OSError, sqlite3.Error) as error:
            raise self._unavailable("request handoff") from error

    async def claim(
        self,
        key: ConversationKey,
        *,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        try:
            return await asyncio.to_thread(
                self._claim_sync,
                key,
                operator,
                occurred_at,
            )
        except (OSError, sqlite3.Error) as error:
            raise self._unavailable("claim handoff") from error

    async def resume_ai(
        self,
        key: ConversationKey,
        *,
        operator: str,
        risk_acknowledged: bool,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        try:
            return await asyncio.to_thread(
                self._resume_ai_sync,
                key,
                operator,
                risk_acknowledged,
                occurred_at,
            )
        except (OSError, sqlite3.Error) as error:
            raise self._unavailable("resume ai") from error

    async def close(
        self,
        key: ConversationKey,
        *,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        try:
            return await asyncio.to_thread(
                self._close_sync,
                key,
                operator,
                occurred_at,
            )
        except (OSError, sqlite3.Error) as error:
            raise self._unavailable("close conversation") from error

    async def queue(self) -> tuple[HandoffQueueItem, ...]:
        try:
            return await asyncio.to_thread(self._queue_sync)
        except (OSError, sqlite3.Error) as error:
            raise self._unavailable("read queue") from error

    async def audit_for(
        self,
        key: ConversationKey,
    ) -> tuple[HandoffAuditEvent, ...]:
        try:
            return await asyncio.to_thread(self._audit_for_sync, key)
        except (OSError, sqlite3.Error) as error:
            raise self._unavailable("read audit") from error

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
        schema_v1 = SCHEMA_V1_PATH.read_text(encoding="utf-8")
        schema_v2 = SCHEMA_V2_PATH.read_text(encoding="utf-8")
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                connection.executescript(schema_v1)
                connection.executescript(schema_v2)
            elif version == 1:
                connection.executescript(schema_v2)
            elif version == SCHEMA_VERSION:
                self._validate_schema(connection)
            else:
                raise RuntimeError("Unsupported connector schema version")

    def _state_sync(
        self,
        key: ConversationKey,
    ) -> ConversationHandoffState | None:
        with self._connect() as connection:
            row = self._select_state(connection, key)
        return None if row is None else self._state_from_row(row)

    def _ensure_ai_sync(
        self,
        key: ConversationKey,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._select_state(connection, key)
            if existing is not None:
                connection.commit()
                return self._state_from_row(existing)
            self._upsert_state(
                connection,
                key=key,
                mode=ConversationMode.AI,
                risk_level=HandoffRiskLevel.LOW,
                reason=None,
                occurred_at=occurred_at,
            )
            self._insert_audit(
                connection,
                key=key,
                event="conversation_initialized",
                from_mode=None,
                to_mode=ConversationMode.AI,
                reason=None,
                risk_level=HandoffRiskLevel.LOW,
                operator="test-system",
                occurred_at=occurred_at,
            )
            state = self._required_state(connection, key)
            connection.commit()
            return self._state_from_row(state)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _request_handoff_sync(
        self,
        key: ConversationKey,
        reason: HandoffReason,
        risk_level: HandoffRiskLevel,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        self._require_synthetic_operator(operator)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._select_state(connection, key)
            current_mode = (
                ConversationMode.AI
                if existing is None
                else ConversationMode(str(existing["mode"]))
            )
            if current_mode is ConversationMode.CLOSED:
                raise HandoffTransitionError(
                    "Closed conversation cannot request handoff"
                )
            if current_mode in {
                ConversationMode.WAITING_HUMAN,
                ConversationMode.HUMAN,
            }:
                connection.commit()
                return self._state_from_row(self._required_state(connection, key))

            self._set_lease_owner(
                connection,
                key,
                ReplyOwner.HUMAN,
                occurred_at,
            )
            self._upsert_state(
                connection,
                key=key,
                mode=ConversationMode.WAITING_HUMAN,
                risk_level=risk_level,
                reason=reason,
                occurred_at=occurred_at,
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO handoff_queue (
                    shop_id,
                    buyer_id,
                    conversation_id,
                    status,
                    reason_code,
                    risk_level,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key.shop_id,
                    key.buyer_id,
                    key.conversation_id,
                    HandoffQueueStatus.WAITING.value,
                    reason.value,
                    risk_level.value,
                    occurred_at.isoformat(),
                ),
            )
            self._insert_audit(
                connection,
                key=key,
                event="handoff_requested",
                from_mode=current_mode,
                to_mode=ConversationMode.WAITING_HUMAN,
                reason=reason,
                risk_level=risk_level,
                operator=operator,
                occurred_at=occurred_at,
            )
            state = self._required_state(connection, key)
            connection.commit()
            return self._state_from_row(state)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _claim_sync(
        self,
        key: ConversationKey,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        self._require_synthetic_operator(operator)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._required_state(connection, key)
            current_mode = ConversationMode(str(existing["mode"]))
            if current_mode is not ConversationMode.WAITING_HUMAN:
                raise HandoffTransitionError(
                    "Only a waiting conversation can be claimed"
                )
            risk_level = HandoffRiskLevel(str(existing["risk_level"]))
            reason = HandoffReason(str(existing["reason_code"]))
            self._upsert_state(
                connection,
                key=key,
                mode=ConversationMode.HUMAN,
                risk_level=risk_level,
                reason=reason,
                occurred_at=occurred_at,
            )
            updated = connection.execute(
                """
                UPDATE handoff_queue
                SET status = ?, claimed_by = ?, claimed_at = ?
                WHERE
                    shop_id = ?
                    AND buyer_id = ?
                    AND conversation_id = ?
                    AND status = ?
                """,
                (
                    HandoffQueueStatus.CLAIMED.value,
                    operator,
                    occurred_at.isoformat(),
                    key.shop_id,
                    key.buyer_id,
                    key.conversation_id,
                    HandoffQueueStatus.WAITING.value,
                ),
            )
            if updated.rowcount != 1:
                raise HandoffTransitionError("Waiting queue item is unavailable")
            self._insert_audit(
                connection,
                key=key,
                event="handoff_claimed",
                from_mode=ConversationMode.WAITING_HUMAN,
                to_mode=ConversationMode.HUMAN,
                reason=reason,
                risk_level=risk_level,
                operator=operator,
                occurred_at=occurred_at,
            )
            state = self._required_state(connection, key)
            connection.commit()
            return self._state_from_row(state)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _resume_ai_sync(
        self,
        key: ConversationKey,
        operator: str,
        risk_acknowledged: bool,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        self._require_synthetic_operator(operator)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._required_state(connection, key)
            current_mode = ConversationMode(str(existing["mode"]))
            if current_mode not in {
                ConversationMode.WAITING_HUMAN,
                ConversationMode.HUMAN,
            }:
                raise HandoffTransitionError(
                    "Conversation is not in a resumable human mode"
                )
            risk_level = HandoffRiskLevel(str(existing["risk_level"]))
            if (
                risk_level in {HandoffRiskLevel.HIGH, HandoffRiskLevel.CRITICAL}
                and not risk_acknowledged
            ):
                raise HandoffTransitionError(
                    "High-risk conversation requires explicit acknowledgement"
                )
            reason_value = existing["reason_code"]
            reason = None if reason_value is None else HandoffReason(str(reason_value))
            self._set_lease_owner(
                connection,
                key,
                ReplyOwner.AI,
                occurred_at,
            )
            self._upsert_state(
                connection,
                key=key,
                mode=ConversationMode.AI,
                risk_level=risk_level,
                reason=reason,
                occurred_at=occurred_at,
            )
            connection.execute(
                """
                UPDATE handoff_queue
                SET status = ?, closed_at = ?
                WHERE
                    shop_id = ?
                    AND buyer_id = ?
                    AND conversation_id = ?
                    AND status IN (?, ?)
                """,
                (
                    HandoffQueueStatus.CLOSED.value,
                    occurred_at.isoformat(),
                    key.shop_id,
                    key.buyer_id,
                    key.conversation_id,
                    HandoffQueueStatus.WAITING.value,
                    HandoffQueueStatus.CLAIMED.value,
                ),
            )
            self._insert_audit(
                connection,
                key=key,
                event="ai_resumed",
                from_mode=current_mode,
                to_mode=ConversationMode.AI,
                reason=reason,
                risk_level=risk_level,
                operator=operator,
                occurred_at=occurred_at,
            )
            state = self._required_state(connection, key)
            connection.commit()
            return self._state_from_row(state)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _close_sync(
        self,
        key: ConversationKey,
        operator: str,
        occurred_at: datetime,
    ) -> ConversationHandoffState:
        self._require_synthetic_operator(operator)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._required_state(connection, key)
            current_mode = ConversationMode(str(existing["mode"]))
            if current_mode is ConversationMode.CLOSED:
                raise HandoffTransitionError("Conversation is already closed")
            risk_level = HandoffRiskLevel(str(existing["risk_level"]))
            reason_value = existing["reason_code"]
            reason = None if reason_value is None else HandoffReason(str(reason_value))
            self._set_lease_owner(
                connection,
                key,
                ReplyOwner.HUMAN,
                occurred_at,
            )
            self._upsert_state(
                connection,
                key=key,
                mode=ConversationMode.CLOSED,
                risk_level=risk_level,
                reason=reason,
                occurred_at=occurred_at,
            )
            connection.execute(
                """
                UPDATE handoff_queue
                SET status = ?, closed_at = ?
                WHERE
                    shop_id = ?
                    AND buyer_id = ?
                    AND conversation_id = ?
                    AND status IN (?, ?)
                """,
                (
                    HandoffQueueStatus.CLOSED.value,
                    occurred_at.isoformat(),
                    key.shop_id,
                    key.buyer_id,
                    key.conversation_id,
                    HandoffQueueStatus.WAITING.value,
                    HandoffQueueStatus.CLAIMED.value,
                ),
            )
            self._insert_audit(
                connection,
                key=key,
                event="conversation_closed",
                from_mode=current_mode,
                to_mode=ConversationMode.CLOSED,
                reason=reason,
                risk_level=risk_level,
                operator=operator,
                occurred_at=occurred_at,
            )
            state = self._required_state(connection, key)
            connection.commit()
            return self._state_from_row(state)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _queue_sync(self) -> tuple[HandoffQueueItem, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM handoff_queue
                WHERE status IN (?, ?)
                ORDER BY queue_id
                """,
                (
                    HandoffQueueStatus.WAITING.value,
                    HandoffQueueStatus.CLAIMED.value,
                ),
            ).fetchall()
        return tuple(self._queue_from_row(row) for row in rows)

    def _audit_for_sync(
        self,
        key: ConversationKey,
    ) -> tuple[HandoffAuditEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM handoff_audit_events
                WHERE
                    shop_id = ?
                    AND buyer_id = ?
                    AND conversation_id = ?
                ORDER BY audit_id
                """,
                (key.shop_id, key.buyer_id, key.conversation_id),
            ).fetchall()
        return tuple(self._audit_from_row(row) for row in rows)

    @staticmethod
    def _select_state(
        connection: sqlite3.Connection,
        key: ConversationKey,
    ) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            connection.execute(
                """
                SELECT *
                FROM conversation_handoff_states
                WHERE
                    shop_id = ?
                    AND buyer_id = ?
                    AND conversation_id = ?
                """,
                (key.shop_id, key.buyer_id, key.conversation_id),
            ).fetchone(),
        )

    @classmethod
    def _required_state(
        cls,
        connection: sqlite3.Connection,
        key: ConversationKey,
    ) -> sqlite3.Row:
        row = cls._select_state(connection, key)
        if row is None:
            raise HandoffNotFoundError("Conversation handoff state does not exist")
        return row

    @staticmethod
    def _upsert_state(
        connection: sqlite3.Connection,
        *,
        key: ConversationKey,
        mode: ConversationMode,
        risk_level: HandoffRiskLevel,
        reason: HandoffReason | None,
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO conversation_handoff_states (
                shop_id,
                buyer_id,
                conversation_id,
                mode,
                risk_level,
                reason_code,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (shop_id, buyer_id, conversation_id)
            DO UPDATE SET
                mode = excluded.mode,
                risk_level = excluded.risk_level,
                reason_code = excluded.reason_code,
                updated_at = excluded.updated_at
            """,
            (
                key.shop_id,
                key.buyer_id,
                key.conversation_id,
                mode.value,
                risk_level.value,
                None if reason is None else reason.value,
                occurred_at.isoformat(),
            ),
        )

    @staticmethod
    def _set_lease_owner(
        connection: sqlite3.Connection,
        key: ConversationKey,
        owner: ReplyOwner,
        occurred_at: datetime,
    ) -> int:
        row = connection.execute(
            """
            SELECT epoch
            FROM reply_leases
            WHERE shop_id = ? AND buyer_id = ? AND conversation_id = ?
            """,
            (key.shop_id, key.buyer_id, key.conversation_id),
        ).fetchone()
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
                occurred_at.isoformat(),
            ),
        )
        return epoch

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        *,
        key: ConversationKey,
        event: str,
        from_mode: ConversationMode | None,
        to_mode: ConversationMode,
        reason: HandoffReason | None,
        risk_level: HandoffRiskLevel,
        operator: str,
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO handoff_audit_events (
                shop_id,
                buyer_id,
                conversation_id,
                event,
                from_mode,
                to_mode,
                reason_code,
                risk_level,
                operator,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key.shop_id,
                key.buyer_id,
                key.conversation_id,
                event,
                None if from_mode is None else from_mode.value,
                to_mode.value,
                None if reason is None else reason.value,
                risk_level.value,
                operator,
                occurred_at.isoformat(),
            ),
        )

    @staticmethod
    def _state_from_row(row: sqlite3.Row) -> ConversationHandoffState:
        reason_value = row["reason_code"]
        return ConversationHandoffState(
            key=ConversationKey(
                shop_id=str(row["shop_id"]),
                buyer_id=str(row["buyer_id"]),
                conversation_id=str(row["conversation_id"]),
            ),
            mode=ConversationMode(str(row["mode"])),
            risk_level=HandoffRiskLevel(str(row["risk_level"])),
            reason=(None if reason_value is None else HandoffReason(str(reason_value))),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _queue_from_row(row: sqlite3.Row) -> HandoffQueueItem:
        claimed_at = row["claimed_at"]
        claimed_by = row["claimed_by"]
        return HandoffQueueItem(
            queue_id=int(row["queue_id"]),
            key=ConversationKey(
                shop_id=str(row["shop_id"]),
                buyer_id=str(row["buyer_id"]),
                conversation_id=str(row["conversation_id"]),
            ),
            status=HandoffQueueStatus(str(row["status"])),
            reason=HandoffReason(str(row["reason_code"])),
            risk_level=HandoffRiskLevel(str(row["risk_level"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            claimed_by=None if claimed_by is None else str(claimed_by),
            claimed_at=(
                None if claimed_at is None else datetime.fromisoformat(str(claimed_at))
            ),
        )

    @staticmethod
    def _audit_from_row(row: sqlite3.Row) -> HandoffAuditEvent:
        from_mode = row["from_mode"]
        reason = row["reason_code"]
        return HandoffAuditEvent(
            audit_id=int(row["audit_id"]),
            key=ConversationKey(
                shop_id=str(row["shop_id"]),
                buyer_id=str(row["buyer_id"]),
                conversation_id=str(row["conversation_id"]),
            ),
            event=str(row["event"]),
            from_mode=(None if from_mode is None else ConversationMode(str(from_mode))),
            to_mode=ConversationMode(str(row["to_mode"])),
            reason=None if reason is None else HandoffReason(str(reason)),
            risk_level=HandoffRiskLevel(str(row["risk_level"])),
            operator=str(row["operator"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _require_synthetic_operator(operator: str) -> None:
        if not operator.strip().casefold().startswith(("fake-", "test-")):
            raise HandoffTransitionError(
                "Handoff operator must be an explicit FAKE or TEST identity"
            )

    @staticmethod
    def _unavailable(operation: str) -> HandoffPersistenceError:
        return HandoffPersistenceError(
            f"Handoff persistence unavailable during {operation}"
        )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        expected = {
            "conversation_handoff_states",
            "handoff_queue",
            "handoff_audit_events",
        }
        actual = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }
        if not expected <= actual:
            raise RuntimeError("Connector handoff schema is incomplete")
