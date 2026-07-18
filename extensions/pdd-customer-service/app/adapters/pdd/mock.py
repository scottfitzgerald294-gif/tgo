"""In-memory PDD adapter for synthetic local tests only."""

from app.models import (
    ConversationKey,
    ConversationMessage,
    ConversationTranscript,
    NormalizedMessage,
    OutboundMessage,
)


class MockPddAdapter:
    """Record synthetic inbound and outbound messages in process memory."""

    def __init__(self) -> None:
        self._messages: dict[ConversationKey, list[ConversationMessage]] = {}
        self._inbound_count = 0
        self._outbound_count = 0

    @property
    def inbound_count(self) -> int:
        return self._inbound_count

    @property
    def outbound_count(self) -> int:
        return self._outbound_count

    async def receive(self, message: NormalizedMessage) -> None:
        key = ConversationKey(
            shop_id=message.shop_id,
            buyer_id=message.buyer_id,
            conversation_id=message.conversation_id,
        )
        self._messages.setdefault(key, []).append(
            ConversationMessage(
                direction="buyer",
                message_id=message.message_id,
                timestamp=message.timestamp,
                content=message.content,
            )
        )
        self._inbound_count += 1

    async def send(self, message: OutboundMessage) -> None:
        key = ConversationKey(
            shop_id=message.shop_id,
            buyer_id=message.buyer_id,
            conversation_id=message.conversation_id,
        )
        self._messages.setdefault(key, []).append(
            ConversationMessage(
                direction="service",
                message_id=str(message.reply_id),
                timestamp=message.timestamp,
                content=message.content,
            )
        )
        self._outbound_count += 1

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None:
        messages = self._messages.get(key)
        if messages is None:
            return None
        return ConversationTranscript(key=key, messages=tuple(messages))
