"""FastAPI application factory for the connector extension."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create an application without external startup side effects."""
    return FastAPI(
        title="PDD Customer Service Connector",
        version="0.1.0",
    )


app = create_app()
