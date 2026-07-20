"""Local-only HTTP routes for deterministic human handoff."""

from typing import Protocol

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.models import (
    ConversationHandoffState,
    ConversationKey,
    HandoffQueueItem,
    RoutingContext,
    RoutingDecision,
)
from app.models.messages import Identifier
from app.repositories import (
    HandoffNotFoundError,
    HandoffTransitionError,
)
from app.services import HandoffUnavailableError


class HandoffApiService(Protocol):
    """Transport-facing subset of handoff orchestration."""

    async def evaluate_and_route(
        self,
        context: RoutingContext,
    ) -> RoutingDecision: ...

    async def state(
        self,
        key: ConversationKey,
    ) -> ConversationHandoffState | None: ...

    async def queue(self) -> tuple[HandoffQueueItem, ...]: ...

    async def claim(
        self,
        key: ConversationKey,
        *,
        operator: str,
    ) -> ConversationHandoffState: ...

    async def resume_ai(
        self,
        key: ConversationKey,
        *,
        operator: str,
        risk_acknowledged: bool,
    ) -> ConversationHandoffState: ...

    async def close(
        self,
        key: ConversationKey,
        *,
        operator: str,
    ) -> ConversationHandoffState: ...


class HandoffOperatorRequest(BaseModel):
    """Explicit synthetic staff operation."""

    model_config = ConfigDict(extra="forbid")

    operator: Identifier


class HandoffResumeRequest(HandoffOperatorRequest):
    """Explicit AI resume with high-risk acknowledgement."""

    risk_acknowledged: bool


def create_handoff_router(service: HandoffApiService) -> APIRouter:
    """Bind one injected handoff service to local-only routes."""

    router = APIRouter(prefix="/handoff", tags=["handoff"])

    @router.post("/evaluate", response_model=RoutingDecision)
    async def evaluate(context: RoutingContext) -> RoutingDecision:
        _require_synthetic_key(context.conversation_key)
        try:
            return await service.evaluate_and_route(context)
        except HandoffUnavailableError as error:
            raise _unavailable() from error
        except HandoffTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/queue", response_model=list[HandoffQueueItem])
    async def queue() -> tuple[HandoffQueueItem, ...]:
        try:
            return await service.queue()
        except HandoffUnavailableError as error:
            raise _unavailable() from error

    @router.get(
        "/conversations/{shop_id}/{buyer_id}/{conversation_id}",
        response_model=ConversationHandoffState,
    )
    async def state(
        shop_id: str,
        buyer_id: str,
        conversation_id: str,
    ) -> ConversationHandoffState:
        key = _key(shop_id, buyer_id, conversation_id)
        try:
            current = await service.state(key)
        except HandoffUnavailableError as error:
            raise _unavailable() from error
        if current is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return current

    @router.post(
        "/conversations/{shop_id}/{buyer_id}/{conversation_id}/claim",
        response_model=ConversationHandoffState,
    )
    async def claim(
        shop_id: str,
        buyer_id: str,
        conversation_id: str,
        request: HandoffOperatorRequest,
    ) -> ConversationHandoffState:
        key = _key(shop_id, buyer_id, conversation_id)
        try:
            return await service.claim(key, operator=request.operator)
        except HandoffNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Conversation not found"
            ) from error
        except HandoffTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except HandoffUnavailableError as error:
            raise _unavailable() from error

    @router.post(
        "/conversations/{shop_id}/{buyer_id}/{conversation_id}/resume",
        response_model=ConversationHandoffState,
    )
    async def resume(
        shop_id: str,
        buyer_id: str,
        conversation_id: str,
        request: HandoffResumeRequest,
    ) -> ConversationHandoffState:
        key = _key(shop_id, buyer_id, conversation_id)
        try:
            return await service.resume_ai(
                key,
                operator=request.operator,
                risk_acknowledged=request.risk_acknowledged,
            )
        except HandoffNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Conversation not found"
            ) from error
        except HandoffTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except HandoffUnavailableError as error:
            raise _unavailable() from error

    @router.post(
        "/conversations/{shop_id}/{buyer_id}/{conversation_id}/close",
        response_model=ConversationHandoffState,
    )
    async def close(
        shop_id: str,
        buyer_id: str,
        conversation_id: str,
        request: HandoffOperatorRequest,
    ) -> ConversationHandoffState:
        key = _key(shop_id, buyer_id, conversation_id)
        try:
            return await service.close(key, operator=request.operator)
        except HandoffNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Conversation not found"
            ) from error
        except HandoffTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except HandoffUnavailableError as error:
            raise _unavailable() from error

    return router


def _key(
    shop_id: str,
    buyer_id: str,
    conversation_id: str,
) -> ConversationKey:
    key = ConversationKey(
        shop_id=shop_id,
        buyer_id=buyer_id,
        conversation_id=conversation_id,
    )
    _require_synthetic_key(key)
    return key


def _require_synthetic_key(key: ConversationKey) -> None:
    if not all(
        value.casefold().startswith(("fake-", "test-"))
        for value in (key.shop_id, key.buyer_id, key.conversation_id)
    ):
        raise HTTPException(
            status_code=422,
            detail="Handoff identifiers must be explicit FAKE or TEST values",
        )


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Human handoff is temporarily unavailable",
    )
