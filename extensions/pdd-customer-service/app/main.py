"""FastAPI application factory for the connector extension."""

from fastapi import FastAPI

from app.adapters.pdd import MockPddAdapter, PddAdapter
from app.api.health import router as health_router
from app.api.simulator import create_simulator_router
from app.repositories import (
    ConversationRepository,
    InMemoryConversationRepository,
)
from app.services import PddSimulatorService


def create_app(
    *,
    pdd_adapter: PddAdapter | None = None,
    conversation_repository: ConversationRepository | None = None,
) -> FastAPI:
    """Create an application without external startup side effects."""
    adapter = pdd_adapter if pdd_adapter is not None else MockPddAdapter()
    repository = (
        conversation_repository
        if conversation_repository is not None
        else InMemoryConversationRepository()
    )
    simulator_service = PddSimulatorService(
        adapter=adapter,
        repository=repository,
    )
    application = FastAPI(
        title="PDD Customer Service Connector",
        version="0.1.0",
    )
    application.include_router(health_router)
    application.include_router(create_simulator_router(simulator_service))
    return application


app = create_app()
