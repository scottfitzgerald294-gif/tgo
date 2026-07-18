"""HTTP routes for the in-process PDD message simulator."""

from typing import Protocol

from fastapi import APIRouter, HTTPException

from app.models import (
    ConversationKey,
    ConversationTranscript,
    PddTextMessageRequest,
    SimulationResult,
)
from app.services import ReliabilityUnavailableError, ReplayWindowError


class SimulatorService(Protocol):
    """Transport-facing subset shared by simple and reliable simulators."""

    async def process(
        self,
        request: PddTextMessageRequest,
    ) -> SimulationResult: ...

    async def transcript(
        self,
        key: ConversationKey,
    ) -> ConversationTranscript | None: ...


def create_simulator_router(service: SimulatorService) -> APIRouter:
    """Bind one injected simulator service to local-only HTTP routes."""
    router = APIRouter(prefix="/simulator", tags=["simulator"])

    @router.post("/messages", response_model=SimulationResult, status_code=201)
    async def process_message(
        message: PddTextMessageRequest,
    ) -> SimulationResult:
        try:
            return await service.process(message)
        except ReplayWindowError as error:
            raise HTTPException(status_code=409, detail=error.reason) from error
        except ReliabilityUnavailableError as error:
            raise HTTPException(
                status_code=503,
                detail="Reliable message processing is temporarily unavailable",
            ) from error

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
