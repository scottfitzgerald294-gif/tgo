"""Shared test fixtures."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def application() -> FastAPI:
    """Return a fresh application for each test."""
    return create_app()


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    """Exercise the ASGI application without an external network."""
    with TestClient(application) as test_client:
        yield test_client
