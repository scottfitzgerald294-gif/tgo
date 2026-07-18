"""FastAPI application factory for the connector extension."""

from fastapi import FastAPI

from app.api.health import router as health_router


def create_app() -> FastAPI:
    """Create an application without external startup side effects."""
    application = FastAPI(
        title="PDD Customer Service Connector",
        version="0.1.0",
    )
    application.include_router(health_router)
    return application


app = create_app()
