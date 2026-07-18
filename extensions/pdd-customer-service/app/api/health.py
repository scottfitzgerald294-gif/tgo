"""Dependency-free service health endpoint."""

from fastapi import APIRouter

from app.models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Report process health without calling external systems."""
    return HealthResponse()
