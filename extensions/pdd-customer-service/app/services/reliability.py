"""Durable orchestration for the synthetic local PDD simulator."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from app.adapters.pdd import MockPddSendError, PddAdapter
from app.models import (
    ConversationKey,
    ConversationTranscript,
    MessageStatus,
    NormalizedMessage,
    OutboundMessage,
    PddTextMessageRequest,
    RecoverySummary,
    ReliabilityRecord,
    ReplyOwner,
    RetryPolicy,
    SimulationResult,
)
from app.repositories import (
    ConversationRepository,
    PersistenceUnavailableError,
    ReliabilityStore,
)
from app.services.simulator import FIXED_REPLY

logger = logging.getLogger(__name__)


class Clock(Protocol):
    """Injectable UTC clock used by reliability processing."""

    def now(self) -> datetime: ...

    async def sleep(self, delay_seconds: float) -> None: ...


class SystemClock:
    """Production local clock using timezone-aware UTC values."""

    def now(self) -> datetime:
        from datetime import UTC

        return datetime.now(UTC)

    async def sleep(self, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)


class ConversationLockRegistry:
    """Maintain one in-process lock for each complete conversation key."""

    def __init__(self) -> None:
        self._locks: dict[ConversationKey, asyncio.Lock] = {}

    def lock_for(self, key: ConversationKey) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock


class ReplayWindowError(ValueError):
    """Raised when a synthetic timestamp is outside the local replay window."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ReliabilityUnavailableError(RuntimeError):
    """Raised when no durable ledger is available for safe processing."""


class ReliablePddSimulatorService:
    """Process synthetic messages through a durable Inbox and Outbox."""

    def __init__(
        self,
        *,
        adapter: PddAdapter,
        repository: ConversationRepository,
        store: ReliabilityStore,
        clock: Clock,
        retry_policy: RetryPolicy | None = None,
        lock_registry: ConversationLockRegistry | None = None,
    ) -> None:
        self._adapter = adapter
        self._repository = repository
        self._store = store
        self._clock = clock
        self._retry_policy = retry_policy or RetryPolicy()
        self._lock_registry = lock_registry or ConversationLockRegistry()

    async def process(self, request: PddTextMessageRequest) -> SimulationResult:
        received_at = self._clock.now()
        timestamp_reason = self._retry_policy.timestamp_reason(
            occurred_at=request.timestamp,
            now=received_at,
        )
        if timestamp_reason is not None:
            raise ReplayWindowError(timestamp_reason)
        trace_id = uuid4()
        try:
            claim = await self._store.claim(
                request,
                received_at=received_at,
                trace_id=trace_id,
                reply_id=uuid4(),
                reply_timestamp=received_at,
                reply_content=FIXED_REPLY,
            )
        except PersistenceUnavailableError as error:
            logger.error(
                "reliability_database_unavailable",
                extra={
                    "trace_id": str(trace_id),
                    "operation": "claim",
                    "reason": "database_unavailable",
                },
            )
            raise ReliabilityUnavailableError(
                "Reliable message processing is temporarily unavailable"
            ) from error
        if not claim.is_new:
            return self._result(claim.record, duplicate=True)

        record = claim.record
        try:
            async with self._lock_registry.lock_for(record.conversation_key):
                return await self._process_claimed(record)
        except PersistenceUnavailableError as error:
            logger.error(
                "reliability_database_unavailable",
                extra={
                    "trace_id": str(record.trace_id),
                    "operation": "process",
                    "reason": "database_unavailable",
                },
            )
            raise ReliabilityUnavailableError(
                "Reliable message processing is temporarily unavailable"
            ) from error

    async def _process_claimed(
        self,
        record: ReliabilityRecord,
    ) -> SimulationResult:
        lease_epoch = await self._store.acquire_ai_lease(
            record.conversation_key,
            recorded_at=self._clock.now(),
        )
        if lease_epoch is None:
            record = await self._store.update_delivery(
                record.inbox_id,
                status=MessageStatus.FAILED,
                attempts=record.attempts,
                retryable=False,
                reason="human_owner_blocks_ai",
                next_attempt_at=None,
                lease_epoch=None,
                event="ai_reply_blocked",
                recorded_at=self._clock.now(),
            )
            return self._result(record, duplicate=False)

        normalized = self._normalized(record)
        await self._adapter.receive(normalized)
        record = await self._store.mark_inbound_recorded(
            record.inbox_id,
            recorded_at=self._clock.now(),
        )
        conversation_created = await self._repository.ensure(
            record.conversation_key,
            created_at=record.received_at,
        )
        record = await self._store.mark_conversation_created(
            record.inbox_id,
            conversation_created=conversation_created,
            recorded_at=self._clock.now(),
        )
        return await self._send_record(
            record,
            lease_epoch=lease_epoch,
            start_attempt=1,
        )

    async def _send_record(
        self,
        record: ReliabilityRecord,
        *,
        lease_epoch: int,
        start_attempt: int,
    ) -> SimulationResult:
        for attempt in range(
            start_attempt,
            self._retry_policy.max_attempts + 1,
        ):
            lease_is_current = await self._store.lease_is_current(
                record.conversation_key,
                owner=ReplyOwner.AI,
                epoch=lease_epoch,
            )
            if not lease_is_current:
                record = await self._store.update_delivery(
                    record.inbox_id,
                    status=MessageStatus.FAILED,
                    attempts=record.attempts,
                    retryable=False,
                    reason="reply_lease_changed",
                    next_attempt_at=None,
                    lease_epoch=lease_epoch,
                    event="ai_reply_blocked",
                    recorded_at=self._clock.now(),
                )
                return self._result(record, duplicate=False)
            try:
                await asyncio.wait_for(
                    self._adapter.send(self._outbound(record)),
                    timeout=self._retry_policy.send_timeout_seconds,
                )
            except TimeoutError:
                failure_reason = "send_timeout"
            except MockPddSendError:
                failure_reason = "mock_send_error"
            else:
                record = await self._store.update_delivery(
                    record.inbox_id,
                    status=MessageStatus.SENT,
                    attempts=attempt,
                    retryable=False,
                    reason=None,
                    next_attempt_at=None,
                    lease_epoch=lease_epoch,
                    event="reply_sent",
                    recorded_at=self._clock.now(),
                )
                return self._result(record, duplicate=False)

            record = await self._store.update_delivery(
                record.inbox_id,
                status=MessageStatus.FAILED,
                attempts=attempt,
                retryable=True,
                reason=failure_reason,
                next_attempt_at=None,
                lease_epoch=lease_epoch,
                event="send_failed",
                recorded_at=self._clock.now(),
            )
            if attempt >= self._retry_policy.max_attempts:
                record = await self._store.update_delivery(
                    record.inbox_id,
                    status=MessageStatus.DEAD_LETTER,
                    attempts=attempt,
                    retryable=False,
                    reason=failure_reason,
                    next_attempt_at=None,
                    lease_epoch=lease_epoch,
                    event="dead_lettered",
                    recorded_at=self._clock.now(),
                )
                return self._result(record, duplicate=False)
            delay = self._retry_policy.delay_after_failure(attempt)
            record = await self._store.update_delivery(
                record.inbox_id,
                status=MessageStatus.RETRYING,
                attempts=attempt,
                retryable=True,
                reason=failure_reason,
                next_attempt_at=self._clock.now() + timedelta(seconds=delay),
                lease_epoch=lease_epoch,
                event="retry_scheduled",
                recorded_at=self._clock.now(),
            )
            await self._clock.sleep(delay)
        raise RuntimeError("Retry loop exhausted without a result")

    async def recover_pending(self) -> RecoverySummary:
        """Resume due local Outbox records without repeating inbound effects."""
        records = await self._store.recoverable(now=self._clock.now())
        sent = 0
        failed = 0
        dead_letter = 0
        for record in records:
            async with self._lock_registry.lock_for(record.conversation_key):
                if not record.inbound_recorded:
                    await self._adapter.receive(self._normalized(record))
                    record = await self._store.mark_inbound_recorded(
                        record.inbox_id,
                        recorded_at=self._clock.now(),
                    )
                if not record.conversation_created:
                    conversation_created = await self._repository.ensure(
                        record.conversation_key,
                        created_at=record.received_at,
                    )
                    record = await self._store.mark_conversation_created(
                        record.inbox_id,
                        conversation_created=conversation_created,
                        recorded_at=self._clock.now(),
                    )
                lease_epoch = record.lease_epoch
                if lease_epoch is None:
                    lease_epoch = await self._store.acquire_ai_lease(
                        record.conversation_key,
                        recorded_at=self._clock.now(),
                    )
                if lease_epoch is None:
                    record = await self._store.update_delivery(
                        record.inbox_id,
                        status=MessageStatus.FAILED,
                        attempts=record.attempts,
                        retryable=False,
                        reason="human_owner_blocks_ai",
                        next_attempt_at=None,
                        lease_epoch=None,
                        event="ai_reply_blocked",
                        recorded_at=self._clock.now(),
                    )
                    result = self._result(record, duplicate=False)
                else:
                    result = await self._send_record(
                        record,
                        lease_epoch=lease_epoch,
                        start_attempt=record.attempts + 1,
                    )
            if result.processing_status is MessageStatus.SENT:
                sent += 1
            elif result.processing_status is MessageStatus.DEAD_LETTER:
                dead_letter += 1
            else:
                failed += 1
        return RecoverySummary(
            scanned=len(records),
            sent=sent,
            failed=failed,
            dead_letter=dead_letter,
        )

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None:
        return await self._store.transcript(key)

    async def take_human_ownership(self, key: ConversationKey) -> int:
        """Explicitly prevent AI replies for a complete conversation key."""
        return await self._store.take_human_ownership(
            key,
            recorded_at=self._clock.now(),
        )

    async def release_to_ai(self, key: ConversationKey) -> int:
        """Explicitly create a new AI reply epoch for a conversation."""
        return await self._store.release_to_ai(
            key,
            recorded_at=self._clock.now(),
        )

    @staticmethod
    def _normalized(record: ReliabilityRecord) -> NormalizedMessage:
        return NormalizedMessage(
            message_id=record.key.message_id,
            shop_id=record.key.shop_id,
            buyer_id=record.conversation_key.buyer_id,
            conversation_id=record.conversation_key.conversation_id,
            timestamp=record.occurred_at,
            content=record.content,
            received_at=record.received_at,
            trace_id=record.trace_id,
        )

    @staticmethod
    def _outbound(record: ReliabilityRecord) -> OutboundMessage:
        return OutboundMessage(
            reply_id=record.reply_id,
            trace_id=record.trace_id,
            shop_id=record.key.shop_id,
            buyer_id=record.conversation_key.buyer_id,
            conversation_id=record.conversation_key.conversation_id,
            in_reply_to_message_id=record.key.message_id,
            timestamp=record.reply_timestamp,
            content=record.reply_content,
        )

    @classmethod
    def _result(
        cls,
        record: ReliabilityRecord,
        *,
        duplicate: bool,
    ) -> SimulationResult:
        return SimulationResult(
            trace_id=record.trace_id,
            conversation_created=record.conversation_created,
            normalized_message=cls._normalized(record),
            outbound_message=cls._outbound(record),
            processing_status=record.status,
            duplicate=duplicate,
            attempts=record.attempts,
        )
