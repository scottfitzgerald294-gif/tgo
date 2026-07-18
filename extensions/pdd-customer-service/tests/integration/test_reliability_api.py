"""In-process API tests for durable message reliability."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.pdd import MockPddAdapter
from app.main import create_app
from app.repositories import InMemoryConversationRepository, SQLiteReliabilityStore
from tests.fixtures.reliability import FailOnceClaimStore, FakeClock


def message_payload(*, timestamp: str = "2026-07-18T09:00:00Z") -> dict[str, str]:
    return {
        "message_id": "message-001",
        "shop_id": "shop-test",
        "buyer_id": "buyer-test",
        "conversation_id": "conversation-test",
        "timestamp": timestamp,
        "content": "你好",
    }


@pytest.mark.integration
def test_api_deduplicates_and_reopens_persisted_conversation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "reliability.sqlite3"
    adapter = MockPddAdapter()
    first_application = create_app(
        pdd_adapter=adapter,
        conversation_repository=InMemoryConversationRepository(),
        reliability_store=SQLiteReliabilityStore(database_path),
        clock=FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
    )

    with TestClient(first_application) as client:
        first = client.post("/simulator/messages", json=message_payload())
        duplicate = client.post("/simulator/messages", json=message_payload())

    assert first.status_code == 201
    assert first.json()["duplicate"] is False
    assert first.json()["processing_status"] == "sent"
    assert duplicate.status_code == 201
    assert duplicate.json()["duplicate"] is True
    assert adapter.inbound_count == 1
    assert adapter.outbound_count == 1

    reopened_application = create_app(
        pdd_adapter=MockPddAdapter(),
        conversation_repository=InMemoryConversationRepository(),
        reliability_store=SQLiteReliabilityStore(database_path),
        clock=FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
    )
    with TestClient(reopened_application) as reopened_client:
        transcript = reopened_client.get(
            "/simulator/shops/shop-test/buyers/buyer-test/"
            "conversations/conversation-test"
        )

    assert transcript.status_code == 200
    assert [item["direction"] for item in transcript.json()["messages"]] == [
        "buyer",
        "service",
    ]


@pytest.mark.integration
def test_api_maps_replay_window_to_conflict_without_adapter_call(
    tmp_path: Path,
) -> None:
    adapter = MockPddAdapter()
    application = create_app(
        pdd_adapter=adapter,
        conversation_repository=InMemoryConversationRepository(),
        reliability_store=SQLiteReliabilityStore(tmp_path / "reliability.sqlite3"),
        clock=FakeClock(datetime(2026, 7, 18, 9, 5, 1, tzinfo=UTC)),
    )

    with TestClient(application) as client:
        response = client.post(
            "/simulator/messages",
            json=message_payload(timestamp="2026-07-18T09:00:00Z"),
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "message_too_old"}
    assert adapter.inbound_count == 0
    assert adapter.send_attempt_count == 0


@pytest.mark.integration
def test_api_maps_database_unavailable_to_sanitized_service_unavailable(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "private-name.sqlite3"
    adapter = MockPddAdapter()
    application = create_app(
        pdd_adapter=adapter,
        conversation_repository=InMemoryConversationRepository(),
        reliability_store=FailOnceClaimStore(database_path),
        clock=FakeClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post("/simulator/messages", json=message_payload())

    assert response.status_code == 503
    assert "private-name" not in response.text
    assert "sql" not in response.text.lower()
    assert adapter.inbound_count == 0
    assert adapter.send_attempt_count == 0
