"""Shared test fixtures."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.pdd import MockPddAdapter
from app.main import create_app
from app.repositories import InMemoryConversationRepository, SQLiteReliabilityStore
from tests.fixtures.reliability import FakeClock


@pytest.fixture
def mock_pdd_adapter() -> MockPddAdapter:
    """Return fresh synthetic PDD state for each test."""
    return MockPddAdapter()


@pytest.fixture
def conversation_repository() -> InMemoryConversationRepository:
    """Return a fresh local conversation repository for each test."""
    return InMemoryConversationRepository()


@pytest.fixture
def application(
    tmp_path: Path,
    mock_pdd_adapter: MockPddAdapter,
    conversation_repository: InMemoryConversationRepository,
) -> FastAPI:
    """Return a fresh application for each test."""
    return create_app(
        pdd_adapter=mock_pdd_adapter,
        conversation_repository=conversation_repository,
        reliability_store=SQLiteReliabilityStore(tmp_path / "reliability.sqlite3"),
        clock=FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
    )


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    """Exercise the ASGI application without an external network."""
    with TestClient(application) as test_client:
        yield test_client
