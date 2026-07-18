"""Application orchestration for the local PDD message simulator."""

import logging
from datetime import UTC, datetime
from uuid import uuid4

from app.adapters.pdd import PddAdapter
from app.models import (
    ConversationKey,
    ConversationTranscript,
    NormalizedMessage,
    OutboundMessage,
    PddTextMessageRequest,
    SimulationResult,
)
from app.repositories import ConversationRepository

FIXED_REPLY = "已收到测试消息"

logger = logging.getLogger(__name__)


class PddSimulatorService:
    """Normalize and route one synthetic message through local components."""

    def __init__(
        self,
        *,
        adapter: PddAdapter,
        repository: ConversationRepository,
    ) -> None:
        self._adapter = adapter
        self._repository = repository

    async def process(self, request: PddTextMessageRequest) -> SimulationResult:
        received_at = datetime.now(UTC)
        trace_id = uuid4()
        normalized = NormalizedMessage(
            message_id=request.message_id,
            shop_id=request.shop_id,
            buyer_id=request.buyer_id,
            conversation_id=request.conversation_id,
            timestamp=request.timestamp,
            content=request.content,
            received_at=received_at,
            trace_id=trace_id,
        )
        await self._adapter.receive(normalized)
        logger.info(
            "mock_pdd_message_received",
            extra={
                "trace_id": str(trace_id),
                "message_id": request.message_id,
                "conversation_id": request.conversation_id,
                "direction": "inbound",
            },
        )

        key = ConversationKey(
            shop_id=request.shop_id,
            buyer_id=request.buyer_id,
            conversation_id=request.conversation_id,
        )
        conversation_created = await self._repository.ensure(
            key,
            created_at=received_at,
        )
        outbound = OutboundMessage(
            reply_id=uuid4(),
            trace_id=trace_id,
            shop_id=request.shop_id,
            buyer_id=request.buyer_id,
            conversation_id=request.conversation_id,
            in_reply_to_message_id=request.message_id,
            timestamp=datetime.now(UTC),
            content=FIXED_REPLY,
        )
        await self._adapter.send(outbound)
        logger.info(
            "mock_pdd_reply_sent",
            extra={
                "trace_id": str(trace_id),
                "message_id": request.message_id,
                "conversation_id": request.conversation_id,
                "direction": "outbound",
            },
        )

        return SimulationResult(
            trace_id=trace_id,
            conversation_created=conversation_created,
            normalized_message=normalized,
            outbound_message=outbound,
        )

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None:
        return await self._adapter.transcript(key)
