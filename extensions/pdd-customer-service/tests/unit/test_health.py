"""Unit-level health route contract."""

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute


@pytest.mark.unit
def test_health_route_declares_typed_response(application: FastAPI) -> None:
    """The application must expose a typed health route."""
    health_route = next(
        (
            route
            for route in application.routes
            if isinstance(route, APIRoute) and route.path == "/health"
        ),
        None,
    )

    assert health_route is not None, "GET /health route is missing"
    assert health_route.response_model is not None
