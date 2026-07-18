"""Unit tests for governed synthetic knowledge models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models import (
    ApprovalStatus,
    KnowledgeKind,
    KnowledgeRecord,
    KnowledgeStatus,
    RiskLevel,
)


def build_record(**updates: object) -> KnowledgeRecord:
    values: dict[str, object] = {
        "knowledge_id": "fake-knowledge-001",
        "version": 1,
        "kind": KnowledgeKind.FAQ,
        "title": "FAKE 常见问题",
        "content": "这是仅用于测试的虚构说明。",
        "status": KnowledgeStatus.PUBLISHED,
        "approval_status": ApprovalStatus.APPROVED,
        "applicable_shop": "fake-shop",
        "applicable_product": "*",
        "applicable_sku": "*",
        "source": "FAKE://knowledge/example",
        "effective_at": datetime(2026, 1, 1, tzinfo=UTC),
        "expires_at": datetime(2099, 1, 1, tzinfo=UTC),
        "risk_level": RiskLevel.LOW,
        "allowed_for_auto_reply": True,
        "reviewed_by": "fake-reviewer",
    }
    values.update(updates)
    return KnowledgeRecord.model_validate(values)


@pytest.mark.unit
@pytest.mark.parametrize("kind", tuple(KnowledgeKind))
def test_all_seven_knowledge_kinds_have_required_governance_fields(
    kind: KnowledgeKind,
) -> None:
    record = build_record(kind=kind)

    assert record.kind is kind
    assert set(KnowledgeRecord.model_fields) == {
        "knowledge_id",
        "version",
        "kind",
        "title",
        "content",
        "status",
        "approval_status",
        "applicable_shop",
        "applicable_product",
        "applicable_sku",
        "source",
        "effective_at",
        "expires_at",
        "risk_level",
        "allowed_for_auto_reply",
        "reviewed_by",
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {
            "effective_at": datetime(2026, 1, 1),
            "expires_at": datetime(2099, 1, 1, tzinfo=UTC),
        },
        {
            "effective_at": datetime(2026, 1, 1, tzinfo=UTC),
            "expires_at": datetime(2025, 1, 1, tzinfo=UTC),
        },
        {
            "approval_status": ApprovalStatus.APPROVED,
            "reviewed_by": None,
        },
    ],
)
def test_knowledge_record_rejects_invalid_time_or_missing_approver(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        build_record(**updates)
