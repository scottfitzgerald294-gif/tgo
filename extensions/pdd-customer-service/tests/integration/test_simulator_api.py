"""In-process HTTP tests for the complete local PDD simulator chain."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.pdd import MockPddAdapter
from app.repositories import InMemoryConversationRepository


@pytest.mark.integration
def test_buyer_sends_hello_and_reads_fixed_reply(
    client: TestClient,
    mock_pdd_adapter: MockPddAdapter,
    conversation_repository: InMemoryConversationRepository,
) -> None:
    response = client.post(
        "/simulator/messages",
        json={
            "message_id": "message-001",
            "shop_id": "shop-test",
            "buyer_id": "buyer-test",
            "conversation_id": "conversation-test",
            "timestamp": "2026-07-18T09:00:00Z",
            "content": "你好",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["conversation_created"] is True
    assert body["outbound_message"]["content"] == "已收到测试消息"
    assert mock_pdd_adapter.inbound_count == 1
    assert mock_pdd_adapter.outbound_count == 1
    assert conversation_repository.count == 1

    transcript = client.get(
        "/simulator/shops/shop-test/buyers/buyer-test/conversations/conversation-test"
    )

    assert transcript.status_code == 200
    assert transcript.json()["key"] == {
        "shop_id": "shop-test",
        "buyer_id": "buyer-test",
        "conversation_id": "conversation-test",
    }
    assert [
        (item["direction"], item["content"]) for item in transcript.json()["messages"]
    ] == [
        ("buyer", "你好"),
        ("service", "已收到测试消息"),
    ]


@pytest.mark.integration
def test_unknown_conversation_returns_not_found(application: FastAPI) -> None:
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/simulator/shops/shop-test/buyers/buyer-test/"
            "conversations/missing-conversation"
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


@pytest.mark.integration
def test_message_with_naive_timestamp_is_rejected_before_adapter(
    client: TestClient,
    mock_pdd_adapter: MockPddAdapter,
    conversation_repository: InMemoryConversationRepository,
) -> None:
    response = client.post(
        "/simulator/messages",
        json={
            "message_id": "message-001",
            "shop_id": "shop-test",
            "buyer_id": "buyer-test",
            "conversation_id": "conversation-test",
            "timestamp": "2026-07-18T09:00:00",
            "content": "你好",
        },
    )

    assert response.status_code == 422
    assert mock_pdd_adapter.inbound_count == 0
    assert mock_pdd_adapter.outbound_count == 0
    assert conversation_repository.count == 0
