"""Explicitly disabled real PDD adapter without guessed protocol details."""

from app.models import (
    ConversationKey,
    ConversationTranscript,
    NormalizedMessage,
    OutboundMessage,
)


class RealPddNotConfiguredError(RuntimeError):
    """Raised because no official PDD contract is configured."""


class RealPddAdapter:
    """Reject every operation until an approved official contract exists."""

    async def receive(self, message: NormalizedMessage) -> None:
        raise RealPddNotConfiguredError("Real PDD integration is not configured")

    async def send(self, message: OutboundMessage) -> None:
        raise RealPddNotConfiguredError("Real PDD integration is not configured")

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None:
        raise RealPddNotConfiguredError("Real PDD integration is not configured")
