"""Typed models for deterministic risk routing and human handoff."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models.messages import ConversationKey, Identifier, MessageText


class HandoffRiskLevel(StrEnum):
    """Risk level attached to a deterministic routing decision."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConversationMode(StrEnum):
    """Persistent reply mode for one complete local conversation key."""

    AI = "AI"
    WAITING_HUMAN = "WAITING_HUMAN"
    HUMAN = "HUMAN"
    CLOSED = "CLOSED"


class KnowledgeAvailability(StrEnum):
    """Governed knowledge state supplied to deterministic routing."""

    VALID = "valid"
    MISSING = "missing"
    CONFLICT = "conflict"
    EXPIRED = "expired"


class RoutingAction(StrEnum):
    """Permitted deterministic routing outcomes."""

    CONTINUE_AI = "continue_ai"
    HANDOFF = "handoff"
    BLOCKED = "blocked"


class HandoffQueueStatus(StrEnum):
    """Persistent lifecycle of one local handoff queue item."""

    WAITING = "waiting"
    CLAIMED = "claimed"
    CLOSED = "closed"


class HandoffReason(StrEnum):
    """Stable, body-free reason codes ordered by the approved policy."""

    HUMAN_ALREADY_ACTIVE = "human_already_active"
    HUMAN_REQUESTED = "human_requested"
    COMPLAINT_LEGAL_REGULATORY = "complaint_legal_regulatory"
    REFUND_COMPENSATION_PRICE = "refund_compensation_price"
    ORDER_CHANGE = "order_change"
    PRODUCT_SAFETY_INJURY = "product_safety_injury"
    SEVERE_QUALITY = "severe_quality"
    NO_VALID_KNOWLEDGE = "no_valid_knowledge"
    KNOWLEDGE_CONFLICT = "knowledge_conflict"
    KNOWLEDGE_EXPIRED = "knowledge_expired"
    SERVICE_FAILURE = "service_failure"
    REPEATED_UNRESOLVED = "repeated_unresolved"
    FORBIDDEN_CLAIM = "forbidden_claim"
    CONVERSATION_CLOSED = "conversation_closed"


TEXT_RULE_REASONS = {
    HandoffReason.HUMAN_REQUESTED,
    HandoffReason.COMPLAINT_LEGAL_REGULATORY,
    HandoffReason.REFUND_COMPENSATION_PRICE,
    HandoffReason.ORDER_CHANGE,
    HandoffReason.PRODUCT_SAFETY_INJURY,
    HandoffReason.SEVERE_QUALITY,
}


class TextTransferRule(BaseModel):
    """One ordered keyword group loaded from reviewed configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    priority: int = Field(ge=2, le=7)
    reason_code: HandoffReason
    risk_level: HandoffRiskLevel
    keywords: tuple[MessageText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reason(self) -> Self:
        if self.reason_code not in TEXT_RULE_REASONS:
            raise ValueError("reason_code is not a configured text rule")
        if len({keyword.casefold() for keyword in self.keywords}) != len(self.keywords):
            raise ValueError("keywords must be unique within one rule")
        return self


class TransferRulesConfig(BaseModel):
    """Strict JSON-compatible YAML contract for text transfer rules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    handoff_message: MessageText
    text_rules: tuple[TextTransferRule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        priorities = [rule.priority for rule in self.text_rules]
        reasons = [rule.reason_code for rule in self.text_rules]
        if len(set(priorities)) != len(priorities):
            raise ValueError("text rule priorities must be unique")
        if len(set(reasons)) != len(reasons):
            raise ValueError("text rule reasons must be unique")
        if priorities != sorted(priorities):
            raise ValueError("text rules must be sorted by priority")
        return self


class ForbiddenClaimRule(BaseModel):
    """One reviewed group of phrases forbidden in a candidate reply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: Identifier
    risk_level: HandoffRiskLevel
    phrases: tuple[MessageText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_phrases(self) -> Self:
        if len({phrase.casefold() for phrase in self.phrases}) != len(self.phrases):
            raise ValueError("forbidden phrases must be unique within one claim")
        return self


class ForbiddenClaimsConfig(BaseModel):
    """Strict JSON-compatible YAML contract for forbidden claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    claims: tuple[ForbiddenClaimRule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_claim_ids(self) -> Self:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("forbidden claim ids must be unique")
        return self


class RoutingContext(BaseModel):
    """Typed facts used by the deterministic risk engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_key: ConversationKey
    message_text: MessageText
    knowledge_status: KnowledgeAvailability
    service_available: bool
    unresolved_count: int = Field(ge=0, le=100)
    candidate_reply: MessageText | None = None


class RoutingDecision(BaseModel):
    """Body-safe decision returned by deterministic routing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: RoutingAction
    reason: HandoffReason | None
    risk_level: HandoffRiskLevel
    response_text: MessageText | None


class ConversationHandoffState(BaseModel):
    """Persistent mode and risk state for one conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: ConversationKey
    mode: ConversationMode
    risk_level: HandoffRiskLevel
    reason: HandoffReason | None
    updated_at: AwareDatetime


class HandoffQueueItem(BaseModel):
    """Body-free open queue item shown to a synthetic staff client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_id: int = Field(ge=1)
    key: ConversationKey
    status: HandoffQueueStatus
    reason: HandoffReason
    risk_level: HandoffRiskLevel
    created_at: AwareDatetime
    claimed_by: Identifier | None
    claimed_at: AwareDatetime | None


class HandoffAuditEvent(BaseModel):
    """Append-only handoff audit metadata without message or reply bodies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: int = Field(ge=1)
    key: ConversationKey
    event: str
    from_mode: ConversationMode | None
    to_mode: ConversationMode
    reason: HandoffReason | None
    risk_level: HandoffRiskLevel
    operator: Identifier
    created_at: AwareDatetime
