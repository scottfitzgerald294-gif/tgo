"""Connector-owned repository interfaces."""

from app.repositories.conversations import (
    ConversationRepository,
    InMemoryConversationRepository,
)

__all__ = ["ConversationRepository", "InMemoryConversationRepository"]
