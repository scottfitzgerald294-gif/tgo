"""Connector-owned repository interfaces."""

from app.repositories.conversations import (
    ConversationRepository,
    InMemoryConversationRepository,
)
from app.repositories.handoff import (
    HandoffNotFoundError,
    HandoffPersistenceError,
    HandoffRepository,
    HandoffTransitionError,
    SQLiteHandoffRepository,
)
from app.repositories.knowledge import (
    DuplicateKnowledgeVersionError,
    JsonKnowledgeRepository,
    KnowledgePersistenceError,
    KnowledgeRepository,
    KnowledgeVersionAlreadyActiveError,
    KnowledgeVersionNotFoundError,
)
from app.repositories.reliability import (
    PersistenceUnavailableError,
    ReliabilityStore,
    SQLiteReliabilityStore,
)

__all__ = [
    "ConversationRepository",
    "DuplicateKnowledgeVersionError",
    "InMemoryConversationRepository",
    "HandoffNotFoundError",
    "HandoffPersistenceError",
    "HandoffRepository",
    "HandoffTransitionError",
    "JsonKnowledgeRepository",
    "KnowledgePersistenceError",
    "KnowledgeRepository",
    "KnowledgeVersionAlreadyActiveError",
    "KnowledgeVersionNotFoundError",
    "PersistenceUnavailableError",
    "ReliabilityStore",
    "SQLiteReliabilityStore",
    "SQLiteHandoffRepository",
]
