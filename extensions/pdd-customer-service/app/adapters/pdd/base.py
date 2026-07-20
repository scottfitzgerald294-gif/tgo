"""PDD adapter contract independent of any real protocol."""

from typing import Protocol

from app.models import (
    ConversationKey,
    ConversationTranscript,
    NormalizedMessage,
    OutboundMessage,
)


class PddAdapter(Protocol):
    """Interface shared by local and future officially specified adapters."""

    async def receive(self, message: NormalizedMessage) -> None: ...

    async def send(self, message: OutboundMessage) -> None: ...

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None: ...
