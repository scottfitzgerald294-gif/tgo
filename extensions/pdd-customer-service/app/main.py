"""FastAPI application factory for the connector extension."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.adapters.pdd import MockPddAdapter, PddAdapter
from app.api.health import router as health_router
from app.api.simulator import create_simulator_router
from app.models import RetryPolicy
from app.repositories import (
    ConversationRepository,
    InMemoryConversationRepository,
    ReliabilityStore,
    SQLiteReliabilityStore,
)
from app.services import (
    Clock,
    ReliablePddSimulatorService,
    SystemClock,
)


def create_app(
    *,
    pdd_adapter: PddAdapter | None = None,
    conversation_repository: ConversationRepository | None = None,
    reliability_store: ReliabilityStore | None = None,
    retry_policy: RetryPolicy | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    """Create an application without external startup side effects."""
    adapter = pdd_adapter if pdd_adapter is not None else MockPddAdapter()
    repository = (
        conversation_repository
        if conversation_repository is not None
        else InMemoryConversationRepository()
    )
    configured_database_path = os.getenv("PDD_RELIABILITY_DB_PATH")
    default_database_path = (
        Path(__file__).resolve().parents[1] / ".local" / "pdd-reliability.sqlite3"
    )
    store = (
        reliability_store
        if reliability_store is not None
        else SQLiteReliabilityStore(
            Path(configured_database_path)
            if configured_database_path
            else default_database_path
        )
    )
    simulator_service = ReliablePddSimulatorService(
        adapter=adapter,
        repository=repository,
        store=store,
        retry_policy=retry_policy,
        clock=clock if clock is not None else SystemClock(),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await store.initialize()
        await simulator_service.recover_pending()
        yield

    application = FastAPI(
        title="PDD Customer Service Connector",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(create_simulator_router(simulator_service))
    return application


app = create_app()
