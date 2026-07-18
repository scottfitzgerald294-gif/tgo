"""Health check response models."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Stable, dependency-free service health response."""

    status: Literal["healthy"] = "healthy"
    service: Literal["pdd-customer-service"] = "pdd-customer-service"
