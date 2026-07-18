"""HTTP routes for the in-process PDD message simulator."""

from fastapi import APIRouter, HTTPException

from app.models import (
    ConversationKey,
    ConversationTranscript,
    PddTextMessageRequest,
    SimulationResult,
)
from app.services import PddSimulatorService


def create_simulator_router(service: PddSimulatorService) -> APIRouter:
    """Bind one injected simulator service to local-only HTTP routes."""
    router = APIRouter(prefix="/simulator", tags=["simulator"])

    @router.post("/messages", response_model=SimulationResult, status_code=201)
    async def process_message(
        message: PddTextMessageRequest,
    ) -> SimulationResult:
        return await service.process(message)

    @router.get(
        "/shops/{shop_id}/buyers/{buyer_id}/conversations/{conversation_id}",
        response_model=ConversationTranscript,
    )
    async def get_transcript(
        shop_id: str,
        buyer_id: str,
        conversation_id: str,
    ) -> ConversationTranscript:
        key = ConversationKey(
            shop_id=shop_id,
            buyer_id=buyer_id,
            conversation_id=conversation_id,
        )
        transcript = await service.transcript(key)
        if transcript is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return transcript

    return router
