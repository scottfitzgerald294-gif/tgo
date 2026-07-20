"""Unit tests for knowledge import, eligibility, conflicts, and rollback."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models import KnowledgeScope
from app.repositories import JsonKnowledgeRepository
from app.services import (
    KnowledgeCatalogService,
    KnowledgeImportBlockedError,
    PreviewDigestMismatchError,
)
from tests.fixtures.knowledge import csv_text, knowledge_record, valid_row

NOW = datetime(2026, 7, 18, tzinfo=UTC)
SCOPE = KnowledgeScope(
    shop_id="fake-shop",
    product_id="fake-product",
    sku_id="fake-sku",
)


@pytest.mark.unit
def test_formal_import_requires_exact_preview_and_zero_errors(
    tmp_path: Path,
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    service = KnowledgeCatalogService(repository=repository)
    valid_source = csv_text(valid_row())
    valid_preview = asyncio.run(service.preview_csv(valid_source, now=NOW))

    with pytest.raises(PreviewDigestMismatchError):
        asyncio.run(
            service.import_csv(
                valid_source,
                expected_digest="0" * 64,
                operator="fake-importer",
                now=NOW,
            )
        )
    invalid_source = csv_text(valid_row(source="https://unsafe.example"))
    invalid_preview = asyncio.run(service.preview_csv(invalid_source, now=NOW))
    with pytest.raises(KnowledgeImportBlockedError):
        asyncio.run(
            service.import_csv(
                invalid_source,
                expected_digest=invalid_preview.digest,
                operator="fake-importer",
                now=NOW,
            )
        )

    assert asyncio.run(repository.snapshot()).records == ()

    result = asyncio.run(
        service.import_csv(
            valid_source,
            expected_digest=valid_preview.digest,
            operator="fake-importer",
            now=NOW,
        )
    )

    assert result.imported_count == 1
    assert result.active_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"status": "draft"},
        {"status": "withdrawn"},
        {"approval_status": "pending", "reviewed_by": None},
        {"approval_status": "rejected", "reviewed_by": None},
        {"source": "https://unsafe.example"},
        {"effective_at": datetime(2027, 1, 1, tzinfo=UTC)},
        {
            "effective_at": datetime(2025, 1, 1, tzinfo=UTC),
            "expires_at": datetime(2026, 1, 1, tzinfo=UTC),
        },
        {"risk_level": "high"},
        {"allowed_for_auto_reply": False},
        {"kind": "forbidden_answer"},
        {"kind": "handoff_condition"},
    ],
)
def test_eligible_records_excludes_every_unsafe_governance_state(
    tmp_path: Path,
    updates: dict[str, object],
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    asyncio.run(
        repository.import_records(
            (knowledge_record(**updates),),
            digest="a" * 64,
            operator="fake-importer",
            occurred_at=NOW,
        )
    )
    service = KnowledgeCatalogService(repository=repository)

    assert asyncio.run(service.eligible_records(SCOPE, now=NOW)) == ()


@pytest.mark.unit
def test_eligible_records_returns_only_matching_active_versions(
    tmp_path: Path,
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    asyncio.run(
        repository.import_records(
            (
                knowledge_record(
                    knowledge_id="fake-active",
                    version=1,
                    content="FAKE older active candidate",
                ),
                knowledge_record(
                    knowledge_id="fake-active",
                    version=2,
                    content="FAKE current active record",
                ),
                knowledge_record(
                    knowledge_id="fake-other-shop",
                    applicable_shop="fake-other-shop",
                ),
            ),
            digest="b" * 64,
            operator="fake-importer",
            occurred_at=NOW,
        )
    )
    service = KnowledgeCatalogService(repository=repository)

    eligible = asyncio.run(service.eligible_records(SCOPE, now=NOW))

    assert [(record.knowledge_id, record.version) for record in eligible] == [
        ("fake-active", 2)
    ]


@pytest.mark.unit
def test_eligible_records_excludes_all_records_in_an_active_conflict(
    tmp_path: Path,
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    asyncio.run(
        repository.import_records(
            (
                knowledge_record(
                    knowledge_id="fake-conflict-a",
                    applicable_product="fake-product",
                    applicable_sku="fake-sku",
                    content="FAKE answer A",
                ),
                knowledge_record(
                    knowledge_id="fake-conflict-b",
                    applicable_product="fake-product",
                    applicable_sku="fake-sku",
                    content="FAKE answer B",
                ),
            ),
            digest="c" * 64,
            operator="fake-importer",
            occurred_at=NOW,
        )
    )
    service = KnowledgeCatalogService(repository=repository)

    assert asyncio.run(service.eligible_records(SCOPE, now=NOW)) == ()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("first_updates", "second_updates", "query_time", "expected_ids"),
    [
        (
            {"content": "FAKE same answer"},
            {"content": "FAKE same answer"},
            NOW,
            {"fake-non-conflict-a", "fake-non-conflict-b"},
        ),
        (
            {},
            {"kind": "product"},
            NOW,
            {"fake-non-conflict-a", "fake-non-conflict-b"},
        ),
        (
            {},
            {"applicable_shop": "fake-other-shop"},
            NOW,
            {"fake-non-conflict-a"},
        ),
        (
            {"applicable_product": "fake-product"},
            {"applicable_product": "fake-other-product"},
            NOW,
            {"fake-non-conflict-a"},
        ),
        (
            {"applicable_sku": "fake-sku"},
            {"applicable_sku": "fake-other-sku"},
            NOW,
            {"fake-non-conflict-a"},
        ),
        (
            {"expires_at": datetime(2026, 6, 1, tzinfo=UTC)},
            {"effective_at": datetime(2026, 6, 1, tzinfo=UTC)},
            datetime(2026, 5, 1, tzinfo=UTC),
            {"fake-non-conflict-a"},
        ),
        (
            {},
            {"status": "draft"},
            NOW,
            {"fake-non-conflict-a"},
        ),
        (
            {},
            {"approval_status": "pending", "reviewed_by": None},
            NOW,
            {"fake-non-conflict-a"},
        ),
    ],
)
def test_eligible_records_does_not_overmatch_non_conflicts(
    tmp_path: Path,
    first_updates: dict[str, object],
    second_updates: dict[str, object],
    query_time: datetime,
    expected_ids: set[str],
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    asyncio.run(
        repository.import_records(
            (
                knowledge_record(
                    **{
                        "knowledge_id": "fake-non-conflict-a",
                        "content": "FAKE answer A",
                        **first_updates,
                    }
                ),
                knowledge_record(
                    **{
                        "knowledge_id": "fake-non-conflict-b",
                        "content": "FAKE answer B",
                        **second_updates,
                    }
                ),
            ),
            digest="d" * 64,
            operator="fake-importer",
            occurred_at=NOW,
        )
    )
    service = KnowledgeCatalogService(repository=repository)

    eligible = asyncio.run(service.eligible_records(SCOPE, now=query_time))

    assert {record.knowledge_id for record in eligible} == expected_ids


@pytest.mark.unit
def test_service_rollback_changes_eligibility_and_requires_synthetic_operator(
    tmp_path: Path,
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    asyncio.run(
        repository.import_records(
            (
                knowledge_record(
                    version=1,
                    content="FAKE eligible v1",
                ),
                knowledge_record(
                    version=2,
                    content="FAKE disabled v2",
                    allowed_for_auto_reply=False,
                ),
            ),
            digest="e" * 64,
            operator="fake-importer",
            occurred_at=NOW,
        )
    )
    service = KnowledgeCatalogService(repository=repository)
    before_rejected_attempt = asyncio.run(repository.snapshot())

    with pytest.raises(KnowledgeImportBlockedError):
        asyncio.run(
            service.rollback(
                "fake-knowledge-001",
                to_version=1,
                operator="real-operator",
                now=NOW,
            )
        )
    assert asyncio.run(repository.snapshot()) == before_rejected_attempt

    result = asyncio.run(
        service.rollback(
            "fake-knowledge-001",
            to_version=1,
            operator="test-operator",
            now=NOW,
        )
    )
    eligible = asyncio.run(service.eligible_records(SCOPE, now=NOW))
    snapshot = asyncio.run(repository.snapshot())

    assert (result.from_version, result.to_version) == (2, 1)
    assert [(record.knowledge_id, record.version) for record in eligible] == [
        ("fake-knowledge-001", 1)
    ]
    assert len(snapshot.records) == 2
