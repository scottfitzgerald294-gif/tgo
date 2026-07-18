"""In-process API tests for deterministic handoff and the staff queue."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.pdd import MockPddAdapter
from app.main import create_app
from app.models import ConversationHandoffState, ConversationKey
from app.repositories import (
    HandoffPersistenceError,
    InMemoryConversationRepository,
    SQLiteHandoffRepository,
    SQLiteReliabilityStore,
)
from tests.fixtures.reliability import FakeClock

NOW = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)


class UnavailableStateRepository(SQLiteHandoffRepository):
    """Fail one handoff read without exposing the local database path."""

    async def state(
        self,
        key: ConversationKey,
    ) -> ConversationHandoffState | None:
        del key
        raise HandoffPersistenceError("private sqlite failure")


def evaluation_payload(message_text: str) -> dict[str, object]:
    return {
        "conversation_key": {
            "shop_id": "fake-shop",
            "buyer_id": "fake-buyer",
            "conversation_id": "fake-conversation",
        },
        "message_text": message_text,
        "knowledge_status": "valid",
        "service_available": True,
        "unresolved_count": 0,
        "candidate_reply": None,
    }


def simulator_payload(message_id: str) -> dict[str, str]:
    return {
        "message_id": message_id,
        "shop_id": "fake-shop",
        "buyer_id": "fake-buyer",
        "conversation_id": "fake-conversation",
        "timestamp": "2026-07-18T09:00:00Z",
        "content": "人工等待期间的新消息",
    }


@pytest.mark.integration
def test_handoff_api_routes_refund_to_body_free_queue_and_blocks_ai(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "connector.sqlite3"
    adapter = MockPddAdapter()
    application = create_app(
        pdd_adapter=adapter,
        conversation_repository=InMemoryConversationRepository(),
        reliability_store=SQLiteReliabilityStore(database_path),
        handoff_repository=SQLiteHandoffRepository(database_path),
        clock=FakeClock(NOW),
    )

    with TestClient(application) as client:
        decision = client.post(
            "/handoff/evaluate",
            json=evaluation_payload("我要退款"),
        )
        queue = client.get("/handoff/queue")
        state = client.get(
            "/handoff/conversations/fake-shop/fake-buyer/fake-conversation"
        )
        blocked = client.post(
            "/simulator/messages",
            json=simulator_payload("fake-message-001"),
        )

    assert decision.status_code == 200
    assert decision.json()["action"] == "handoff"
    assert decision.json()["reason"] == "refund_compensation_price"
    assert decision.json()["response_text"].endswith("请稍候。")
    assert queue.status_code == 200
    assert len(queue.json()) == 1
    assert queue.json()[0]["status"] == "waiting"
    assert "message_text" not in queue.text
    assert "我要退款" not in queue.text
    assert state.status_code == 200
    assert state.json()["mode"] == "WAITING_HUMAN"
    assert blocked.status_code == 201
    assert blocked.json()["processing_status"] == "failed"
    assert adapter.send_attempt_count == 0


@pytest.mark.integration
@pytest.mark.parametrize(
    ("message_text", "reason"),
    [
        ("我要退款", "refund_compensation_price"),
        ("我要投诉", "complaint_legal_regulatory"),
        ("帮我改地址", "order_change"),
        ("找真人客服", "human_requested"),
    ],
)
def test_handoff_api_acceptance_phrases_always_route_to_human(
    tmp_path: Path,
    message_text: str,
    reason: str,
) -> None:
    database_path = tmp_path / f"{reason}.sqlite3"
    application = create_app(
        reliability_store=SQLiteReliabilityStore(database_path),
        handoff_repository=SQLiteHandoffRepository(database_path),
        clock=FakeClock(NOW),
    )

    with TestClient(application) as client:
        response = client.post(
            "/handoff/evaluate",
            json=evaluation_payload(message_text),
        )

    assert response.status_code == 200
    assert response.json()["action"] == "handoff"
    assert response.json()["reason"] == reason


@pytest.mark.integration
def test_handoff_api_claim_resume_and_closed_terminal_state(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "connector.sqlite3"
    adapter = MockPddAdapter()
    application = create_app(
        pdd_adapter=adapter,
        conversation_repository=InMemoryConversationRepository(),
        reliability_store=SQLiteReliabilityStore(database_path),
        handoff_repository=SQLiteHandoffRepository(database_path),
        clock=FakeClock(NOW),
    )
    conversation_url = "/handoff/conversations/fake-shop/fake-buyer/fake-conversation"

    with TestClient(application) as client:
        assert (
            client.post(
                "/handoff/evaluate",
                json=evaluation_payload("我要退款"),
            ).status_code
            == 200
        )
        claimed = client.post(
            f"{conversation_url}/claim",
            json={"operator": "fake-staff"},
        )
        rejected_resume = client.post(
            f"{conversation_url}/resume",
            json={
                "operator": "fake-staff",
                "risk_acknowledged": False,
            },
        )
        resumed = client.post(
            f"{conversation_url}/resume",
            json={
                "operator": "fake-staff",
                "risk_acknowledged": True,
            },
        )
        sent = client.post(
            "/simulator/messages",
            json=simulator_payload("fake-message-resumed"),
        )
        closed = client.post(
            f"{conversation_url}/close",
            json={"operator": "fake-staff"},
        )
        blocked = client.post(
            "/simulator/messages",
            json=simulator_payload("fake-message-closed"),
        )
        rejected_closed_resume = client.post(
            f"{conversation_url}/resume",
            json={
                "operator": "fake-staff",
                "risk_acknowledged": True,
            },
        )

    assert claimed.status_code == 200
    assert claimed.json()["mode"] == "HUMAN"
    assert rejected_resume.status_code == 409
    assert resumed.status_code == 200
    assert resumed.json()["mode"] == "AI"
    assert sent.status_code == 201
    assert sent.json()["processing_status"] == "sent"
    assert closed.status_code == 200
    assert closed.json()["mode"] == "CLOSED"
    assert blocked.status_code == 201
    assert blocked.json()["processing_status"] == "failed"
    assert rejected_closed_resume.status_code == 409
    assert adapter.outbound_count == 1


@pytest.mark.integration
def test_handoff_api_maps_unknown_invalid_and_unavailable_safely(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "private-handoff.sqlite3"
    application = create_app(
        reliability_store=SQLiteReliabilityStore(database_path),
        handoff_repository=UnavailableStateRepository(database_path),
        clock=FakeClock(NOW),
    )

    with TestClient(application) as client:
        unavailable = client.post(
            "/handoff/evaluate",
            json=evaluation_payload("普通测试问题"),
        )
        invalid = client.get(
            "/handoff/conversations/real-shop/fake-buyer/fake-conversation"
        )

    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "Human handoff is temporarily unavailable"}
    assert "private-handoff" not in unavailable.text
    assert "普通测试问题" not in unavailable.text
    assert invalid.status_code == 422

    healthy_database = tmp_path / "healthy.sqlite3"
    healthy_application = create_app(
        reliability_store=SQLiteReliabilityStore(healthy_database),
        handoff_repository=SQLiteHandoffRepository(healthy_database),
        clock=FakeClock(NOW),
    )
    with TestClient(healthy_application) as client:
        unknown_state = client.get(
            "/handoff/conversations/fake-shop/fake-buyer/fake-unknown"
        )
        unknown_claim = client.post(
            "/handoff/conversations/fake-shop/fake-buyer/fake-unknown/claim",
            json={"operator": "fake-staff"},
        )

    assert unknown_state.status_code == 404
    assert unknown_claim.status_code == 404
