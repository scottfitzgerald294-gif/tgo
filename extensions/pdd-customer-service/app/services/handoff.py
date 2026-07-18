"""Orchestration for deterministic risk routing and human handoff."""

from app.models import (
    ConversationHandoffState,
    ConversationKey,
    HandoffQueueItem,
    HandoffReason,
    RoutingAction,
    RoutingContext,
    RoutingDecision,
)
from app.repositories import HandoffPersistenceError, HandoffRepository
from app.services.reliability import Clock
from app.services.risk_routing import RiskRuleEngine


class HandoffUnavailableError(RuntimeError):
    """Raised when safe handoff state cannot be persisted or read."""


class HandoffService:
    """Apply deterministic routing and persist every human transition."""

    def __init__(
        self,
        *,
        repository: HandoffRepository,
        engine: RiskRuleEngine,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._engine = engine
        self._clock = clock

    @property
    def handoff_message(self) -> str:
        """Return the fixed reviewed handoff prompt."""

        return self._engine.handoff_message

    async def evaluate_and_route(
        self,
        context: RoutingContext,
    ) -> RoutingDecision:
        """Evaluate one message and atomically persist any handoff."""

        try:
            state = await self._repository.state(context.conversation_key)
            if state is None:
                state = await self._repository.ensure_ai(
                    context.conversation_key,
                    occurred_at=self._clock.now(),
                )
            decision = self._engine.evaluate(
                context,
                current_mode=state.mode,
            )
            if (
                decision.action is RoutingAction.HANDOFF
                and decision.reason is not HandoffReason.HUMAN_ALREADY_ACTIVE
            ):
                reason = decision.reason
                if reason is None:
                    raise RuntimeError("Handoff decision requires a reason")
                await self._repository.request_handoff(
                    context.conversation_key,
                    reason=reason,
                    risk_level=decision.risk_level,
                    operator="test-risk-router",
                    occurred_at=self._clock.now(),
                )
            return decision
        except HandoffPersistenceError as error:
            raise HandoffUnavailableError(
                "Human handoff is temporarily unavailable"
            ) from error

    async def state(
        self,
        key: ConversationKey,
    ) -> ConversationHandoffState | None:
        try:
            return await self._repository.state(key)
        except HandoffPersistenceError as error:
            raise HandoffUnavailableError(
                "Human handoff is temporarily unavailable"
            ) from error

    async def queue(self) -> tuple[HandoffQueueItem, ...]:
        try:
            return await self._repository.queue()
        except HandoffPersistenceError as error:
            raise HandoffUnavailableError(
                "Human handoff is temporarily unavailable"
            ) from error

    async def claim(
        self,
        key: ConversationKey,
        *,
        operator: str,
    ) -> ConversationHandoffState:
        try:
            return await self._repository.claim(
                key,
                operator=operator,
                occurred_at=self._clock.now(),
            )
        except HandoffPersistenceError as error:
            raise HandoffUnavailableError(
                "Human handoff is temporarily unavailable"
            ) from error

    async def resume_ai(
        self,
        key: ConversationKey,
        *,
        operator: str,
        risk_acknowledged: bool,
    ) -> ConversationHandoffState:
        try:
            return await self._repository.resume_ai(
                key,
                operator=operator,
                risk_acknowledged=risk_acknowledged,
                occurred_at=self._clock.now(),
            )
        except HandoffPersistenceError as error:
            raise HandoffUnavailableError(
                "Human handoff is temporarily unavailable"
            ) from error

    async def close(
        self,
        key: ConversationKey,
        *,
        operator: str,
    ) -> ConversationHandoffState:
        try:
            return await self._repository.close(
                key,
                operator=operator,
                occurred_at=self._clock.now(),
            )
        except HandoffPersistenceError as error:
            raise HandoffUnavailableError(
                "Human handoff is temporarily unavailable"
            ) from error
