"""Typed models for the local PDD message simulator."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class ConversationKey(BaseModel):
    """Complete local key that prevents cross-shop or cross-buyer mixing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shop_id: Identifier
    buyer_id: Identifier
    conversation_id: Identifier


class PddTextMessageRequest(BaseModel):
    """Validated text input accepted by the local simulator."""

    model_config = ConfigDict(extra="forbid")

    message_id: Identifier
    shop_id: Identifier
    buyer_id: Identifier
    conversation_id: Identifier
    timestamp: AwareDatetime
    content: MessageText


class NormalizedMessage(PddTextMessageRequest):
    """Stable internal representation of a validated mock PDD message."""

    received_at: AwareDatetime
    trace_id: UUID
    source: Literal["mock-pdd"] = "mock-pdd"


class OutboundMessage(BaseModel):
    """Text reply emitted by the local simulator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reply_id: UUID
    trace_id: UUID
    shop_id: Identifier
    buyer_id: Identifier
    conversation_id: Identifier
    in_reply_to_message_id: Identifier
    timestamp: AwareDatetime
    content: MessageText


class ConversationMessage(BaseModel):
    """One buyer-visible item in an in-memory conversation transcript."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Literal["buyer", "service"]
    message_id: Identifier
    timestamp: AwareDatetime
    content: MessageText


class ConversationTranscript(BaseModel):
    """Immutable snapshot of one complete local conversation key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: ConversationKey
    messages: tuple[ConversationMessage, ...]


class SimulationResult(BaseModel):
    """Result returned after one local simulator request."""

    model_config = ConfigDict(extra="forbid")

    trace_id: UUID
    conversation_created: bool
    normalized_message: NormalizedMessage
    outbound_message: OutboundMessage
