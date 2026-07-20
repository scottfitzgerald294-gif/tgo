"""Conversation repository contracts for the local simulator."""

from datetime import datetime
from typing import Protocol

from app.models import ConversationKey


class ConversationRepository(Protocol):
    """Minimal conversation association boundary."""

    async def ensure(
        self,
        key: ConversationKey,
        *,
        created_at: datetime,
    ) -> bool: ...


class InMemoryConversationRepository:
    """Associate complete synthetic conversation keys in process memory."""

    def __init__(self) -> None:
        self._created_at_by_key: dict[ConversationKey, datetime] = {}

    @property
    def count(self) -> int:
        return len(self._created_at_by_key)

    async def ensure(
        self,
        key: ConversationKey,
        *,
        created_at: datetime,
    ) -> bool:
        if key in self._created_at_by_key:
            return False
        self._created_at_by_key[key] = created_at
        return True
