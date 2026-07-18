"""Synthetic CSV builders for knowledge tests."""

import csv
import io
from datetime import UTC, datetime

from app.models import KnowledgeRecord

KNOWLEDGE_HEADERS = (
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
)


def valid_row(**updates: str) -> dict[str, str]:
    row = {
        "knowledge_id": "fake-knowledge-001",
        "version": "1",
        "kind": "faq",
        "title": "FAKE 常见问题",
        "content": "这是仅用于测试的虚构说明。",
        "status": "published",
        "approval_status": "approved",
        "applicable_shop": "fake-shop",
        "applicable_product": "*",
        "applicable_sku": "*",
        "source": "FAKE://knowledge/example",
        "effective_at": "2026-01-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "risk_level": "low",
        "allowed_for_auto_reply": "true",
        "reviewed_by": "fake-reviewer",
    }
    row.update(updates)
    return row


def csv_text(
    *rows: dict[str, str],
    headers: tuple[str, ...] = KNOWLEDGE_HEADERS,
) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def knowledge_record(**updates: object) -> KnowledgeRecord:
    values: dict[str, object] = {
        **valid_row(),
        "version": 1,
        "allowed_for_auto_reply": True,
        "effective_at": datetime(2026, 1, 1, tzinfo=UTC),
        "expires_at": datetime(2099, 1, 1, tzinfo=UTC),
    }
    values.update(updates)
    return KnowledgeRecord.model_validate(values)
