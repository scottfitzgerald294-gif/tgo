"""In-process API tests for service health."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_health_endpoint_returns_service_status(client: TestClient) -> None:
    """Health checks must be stable and require no external dependency."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "pdd-customer-service",
    }
