"""Unit tests for local simulator conversation association."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.models import ConversationKey
from app.repositories import InMemoryConversationRepository


@pytest.mark.unit
def test_repository_creates_reuses_and_isolates_complete_key() -> None:
    repository = InMemoryConversationRepository()
    key = ConversationKey(
        shop_id="shop-test",
        buyer_id="buyer-a",
        conversation_id="conversation-test",
    )
    other_buyer = ConversationKey(
        shop_id="shop-test",
        buyer_id="buyer-b",
        conversation_id="conversation-test",
    )
    other_shop = ConversationKey(
        shop_id="shop-other",
        buyer_id="buyer-a",
        conversation_id="conversation-test",
    )
    now = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)

    assert asyncio.run(repository.ensure(key, created_at=now)) is True
    assert asyncio.run(repository.ensure(key, created_at=now)) is False
    assert asyncio.run(repository.ensure(other_buyer, created_at=now)) is True
    assert asyncio.run(repository.ensure(other_shop, created_at=now)) is True
    assert repository.count == 3
