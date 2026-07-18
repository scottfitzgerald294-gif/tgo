"""Typed models for durable local message reliability."""

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.messages import (
    ConversationKey,
    Identifier,
    MessageStatus,
    MessageText,
)


class ReplyOwner(StrEnum):
    """Current owner allowed to emit a conversation reply."""

    AI = "ai"
    HUMAN = "human"


class MessageKey(BaseModel):
    """Synthetic per-shop idempotency key used only by the local simulator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shop_id: Identifier
    message_id: Identifier


class RetryPolicy(BaseModel):
    """Validated retry, timeout, and replay-window parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_seconds: float = Field(default=1.0, ge=0)
    max_delay_seconds: float = Field(default=30.0, ge=0)
    send_timeout_seconds: float = Field(default=2.0, gt=0)
    replay_window_seconds: float = Field(default=300.0, ge=0)
    future_tolerance_seconds: float = Field(default=60.0, ge=0)

    def delay_after_failure(self, failed_attempt: int) -> float:
        """Return capped exponential delay after a numbered failed attempt."""
        if failed_attempt < 1:
            raise ValueError("failed_attempt must be at least 1")
        return float(
            min(
                self.base_delay_seconds * (2 ** (failed_attempt - 1)),
                self.max_delay_seconds,
            )
        )

    def timestamp_reason(
        self,
        *,
        occurred_at: datetime,
        now: datetime,
    ) -> str | None:
        """Classify timestamps outside the configured local replay window."""
        if occurred_at < now - timedelta(seconds=self.replay_window_seconds):
            return "message_too_old"
        if occurred_at > now + timedelta(seconds=self.future_tolerance_seconds):
            return "message_from_future"
        return None


class ReliabilityRecord(BaseModel):
    """Complete durable state required to resume one synthetic message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inbox_id: int
    key: MessageKey
    conversation_key: ConversationKey
    occurred_at: AwareDatetime
    content: MessageText
    received_at: AwareDatetime
    trace_id: UUID
    reply_id: UUID
    reply_timestamp: AwareDatetime
    reply_content: MessageText
    status: MessageStatus
    attempts: int
    retryable: bool
    last_reason: str | None
    next_attempt_at: AwareDatetime | None
    lease_epoch: int | None
    inbound_recorded: bool
    conversation_created: bool


class AuditRecord(BaseModel):
    """One body-free append-only reliability audit entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: int
    trace_id: UUID
    event: str
    status: MessageStatus | None
    attempt: int
    reason: str | None
    created_at: AwareDatetime


class ClaimResult(BaseModel):
    """Result of an atomic Inbox claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ReliabilityRecord
    is_new: bool


class RecoverySummary(BaseModel):
    """Counts from one recovery scan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scanned: int = 0
    sent: int = 0
    failed: int = 0
    dead_letter: int = 0
