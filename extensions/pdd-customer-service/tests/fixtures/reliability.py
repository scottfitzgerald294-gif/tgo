"""Synthetic clocks and helpers for reliability tests."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.adapters.pdd import MockPddAdapter
from app.models import (
    ClaimResult,
    OutboundMessage,
    PddTextMessageRequest,
    ReliabilityRecord,
)
from app.repositories import PersistenceUnavailableError, SQLiteReliabilityStore


@dataclass
class FakeClock:
    """Deterministic clock whose sleeps advance virtual time."""

    current: datetime
    sleeps: list[float] = field(default_factory=list)

    def now(self) -> datetime:
        return self.current

    async def sleep(self, delay_seconds: float) -> None:
        self.sleeps.append(delay_seconds)
        self.current += timedelta(seconds=delay_seconds)


@dataclass
class BlockingRetryClock:
    """Advance virtual time, then block so a retrying task can be cancelled."""

    current: datetime
    sleeps: list[float] = field(default_factory=list)
    _sleep_started: asyncio.Event = field(default_factory=asyncio.Event)
    _release: asyncio.Event = field(default_factory=asyncio.Event)

    def now(self) -> datetime:
        return self.current

    async def sleep(self, delay_seconds: float) -> None:
        self.sleeps.append(delay_seconds)
        self.current += timedelta(seconds=delay_seconds)
        self._sleep_started.set()
        await self._release.wait()

    async def wait_until_sleeping(self) -> None:
        await self._sleep_started.wait()


class HangingSendAdapter(MockPddAdapter):
    """Adapter whose outbound call waits until the caller cancels it."""

    def __init__(self) -> None:
        super().__init__()
        self._hanging_send_attempt_count = 0

    @property
    def send_attempt_count(self) -> int:
        return self._hanging_send_attempt_count

    async def send(self, message: OutboundMessage) -> None:
        del message
        self._hanging_send_attempt_count += 1
        await asyncio.Event().wait()


class BlockingSendAdapter(MockPddAdapter):
    """Expose controlled send entry and release for concurrency assertions."""

    def __init__(self, *, expected_concurrent: int) -> None:
        super().__init__()
        self._expected_concurrent = expected_concurrent
        self._active_sends = 0
        self._max_active_sends = 0
        self._expected_entered = asyncio.Event()
        self._release = asyncio.Event()
        self.send_order: list[str] = []

    @property
    def max_active_sends(self) -> int:
        return self._max_active_sends

    async def wait_until_expected_entered(self) -> None:
        await self._expected_entered.wait()

    def release(self) -> None:
        self._release.set()

    async def send(self, message: OutboundMessage) -> None:
        self._active_sends += 1
        self._max_active_sends = max(self._max_active_sends, self._active_sends)
        self.send_order.append(message.in_reply_to_message_id)
        if self._active_sends >= self._expected_concurrent:
            self._expected_entered.set()
        try:
            await self._release.wait()
            await super().send(message)
        finally:
            self._active_sends -= 1


class TakeoverAfterConversationStore(SQLiteReliabilityStore):
    """Simulate human takeover after AI lease but before outbound send."""

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
        await self.take_human_ownership(
            record.conversation_key,
            recorded_at=recorded_at,
        )
        return record


class FailOnceClaimStore(SQLiteReliabilityStore):
    """Raise a fixed persistence outage before the first atomic Claim."""

    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self._fail_next_claim = True

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
        if self._fail_next_claim:
            self._fail_next_claim = False
            raise PersistenceUnavailableError("Synthetic unavailable ledger")
        return await super().claim(
            request,
            received_at=received_at,
            trace_id=trace_id,
            reply_id=reply_id,
            reply_timestamp=reply_timestamp,
            reply_content=reply_content,
        )


class FailOnceInboundMarkStore(SQLiteReliabilityStore):
    """Fail after inbound receipt so the service must stop before sending."""

    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self._fail_next_mark = True

    async def mark_inbound_recorded(
        self,
        inbox_id: int,
        *,
        recorded_at: datetime,
    ) -> ReliabilityRecord:
        if self._fail_next_mark:
            self._fail_next_mark = False
            raise PersistenceUnavailableError("Synthetic unavailable ledger")
        return await super().mark_inbound_recorded(
            inbox_id,
            recorded_at=recorded_at,
        )
