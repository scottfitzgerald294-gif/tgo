"""In-memory PDD adapter for synthetic local tests only."""

from app.models import (
    ConversationKey,
    ConversationMessage,
    ConversationTranscript,
    NormalizedMessage,
    OutboundMessage,
)


class MockPddSendError(RuntimeError):
    """Raised for a configured synthetic outbound failure."""


class MockPddAdapter:
    """Record synthetic inbound and outbound messages in process memory."""

    def __init__(self, *, fail_send_attempts: int = 0) -> None:
        self._messages: dict[ConversationKey, list[ConversationMessage]] = {}
        self._inbound_count = 0
        self._outbound_count = 0
        self._send_attempt_count = 0
        self._fail_send_attempts = fail_send_attempts
        self._delivered_reply_ids: set[str] = set()
        self._received_message_keys: set[tuple[str, str]] = set()

    @property
    def inbound_count(self) -> int:
        return self._inbound_count

    @property
    def outbound_count(self) -> int:
        return self._outbound_count

    @property
    def send_attempt_count(self) -> int:
        return self._send_attempt_count

    async def receive(self, message: NormalizedMessage) -> None:
        message_key = (message.shop_id, message.message_id)
        if message_key in self._received_message_keys:
            return
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
        self._received_message_keys.add(message_key)
        self._inbound_count += 1

    async def send(self, message: OutboundMessage) -> None:
        self._send_attempt_count += 1
        if self._send_attempt_count <= self._fail_send_attempts:
            raise MockPddSendError("Configured synthetic PDD send failure")
        reply_id = str(message.reply_id)
        if reply_id in self._delivered_reply_ids:
            return
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
        self._delivered_reply_ids.add(reply_id)
        self._outbound_count += 1

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None:
        messages = self._messages.get(key)
        if messages is None:
            return None
        return ConversationTranscript(key=key, messages=tuple(messages))
