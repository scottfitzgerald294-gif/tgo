"""Unit tests for knowledge CSV preview and validation."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models import KnowledgeCatalog
from app.repositories import JsonKnowledgeRepository
from app.services import KnowledgeCatalogService
from tests.fixtures.knowledge import csv_text, knowledge_record, valid_row


class SnapshotOnlyRepository:
    """Minimal read-only repository used by preview tests."""

    def __init__(self, catalog: KnowledgeCatalog | None = None) -> None:
        self.snapshot_calls = 0
        self._catalog = catalog or KnowledgeCatalog()

    async def snapshot(self) -> KnowledgeCatalog:
        self.snapshot_calls += 1
        return self._catalog


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "",
        "knowledge_id,version\nfake-knowledge-001,1\n",
    ],
)
def test_preview_reports_missing_csv_headers_without_writing(source: str) -> None:
    repository = SnapshotOnlyRepository()
    service = KnowledgeCatalogService(repository=repository)

    preview = asyncio.run(
        service.preview_csv(
            source,
            now=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )

    assert preview.records == ()
    assert preview.error_count == 1
    assert preview.warning_count == 0
    assert [issue.code for issue in preview.issues] == ["missing_header"]
    assert repository.snapshot_calls == 1


@pytest.mark.unit
def test_preview_parses_valid_row_and_uses_exact_content_digest() -> None:
    repository = SnapshotOnlyRepository()
    service = KnowledgeCatalogService(repository=repository)
    source = csv_text(valid_row())

    first = asyncio.run(
        service.preview_csv(source, now=datetime(2026, 7, 18, tzinfo=UTC))
    )
    second = asyncio.run(
        service.preview_csv(source, now=datetime(2026, 7, 18, tzinfo=UTC))
    )
    changed = asyncio.run(
        service.preview_csv(
            f"{source}\n",
            now=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )

    assert len(first.digest) == 64
    assert first.digest == second.digest
    assert first.digest != changed.digest
    assert first.error_count == 0
    assert len(first.records) == 1
    assert first.records[0].knowledge_id == "fake-knowledge-001"


@pytest.mark.unit
def test_preview_reports_invalid_source_and_batch_or_catalog_duplicates() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    invalid_and_duplicate = csv_text(
        valid_row(source="https://real.example/unsafe"),
        valid_row(source="https://real.example/unsafe"),
    )
    batch_preview = asyncio.run(
        KnowledgeCatalogService(repository=SnapshotOnlyRepository()).preview_csv(
            invalid_and_duplicate,
            now=now,
        )
    )
    valid_preview = asyncio.run(
        KnowledgeCatalogService(repository=SnapshotOnlyRepository()).preview_csv(
            csv_text(valid_row()),
            now=now,
        )
    )
    catalog_preview = asyncio.run(
        KnowledgeCatalogService(
            repository=SnapshotOnlyRepository(
                KnowledgeCatalog(records=valid_preview.records)
            )
        ).preview_csv(
            csv_text(valid_row()),
            now=now,
        )
    )

    assert {issue.code for issue in batch_preview.issues} == {
        "invalid_source",
        "duplicate_in_batch",
    }
    assert {issue.code for issue in catalog_preview.issues} == {"duplicate_in_catalog"}


@pytest.mark.unit
def test_preview_warns_for_every_auto_reply_safety_gate() -> None:
    source = csv_text(
        valid_row(knowledge_id="fake-draft", status="draft"),
        valid_row(
            knowledge_id="fake-unreviewed",
            approval_status="pending",
            reviewed_by="",
        ),
        valid_row(
            knowledge_id="fake-expired",
            effective_at="2025-01-01T00:00:00Z",
            expires_at="2026-01-01T00:00:00Z",
        ),
        valid_row(
            knowledge_id="fake-future",
            effective_at="2027-01-01T00:00:00Z",
        ),
        valid_row(knowledge_id="fake-high", risk_level="high"),
        valid_row(
            knowledge_id="fake-disabled",
            allowed_for_auto_reply="false",
        ),
    )

    preview = asyncio.run(
        KnowledgeCatalogService(repository=SnapshotOnlyRepository()).preview_csv(
            source,
            now=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )

    assert preview.error_count == 0
    assert {issue.code for issue in preview.issues} == {
        "not_published",
        "unreviewed",
        "expired",
        "not_yet_effective",
        "high_risk",
        "auto_reply_disabled",
    }


@pytest.mark.unit
def test_preview_warns_for_every_record_in_a_batch_conflict() -> None:
    source = csv_text(
        valid_row(
            knowledge_id="fake-conflict-a",
            content="FAKE answer A",
        ),
        valid_row(
            knowledge_id="fake-conflict-b",
            content="FAKE answer B",
        ),
    )

    preview = asyncio.run(
        KnowledgeCatalogService(repository=SnapshotOnlyRepository()).preview_csv(
            source,
            now=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )

    conflict_issues = [
        issue for issue in preview.issues if issue.code == "knowledge_conflict"
    ]
    assert preview.error_count == 0
    assert {issue.knowledge_id for issue in conflict_issues} == {
        "fake-conflict-a",
        "fake-conflict-b",
    }


@pytest.mark.unit
def test_preview_warns_when_incoming_record_conflicts_with_active_catalog(
    tmp_path: Path,
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    asyncio.run(
        repository.import_records(
            (
                knowledge_record(
                    knowledge_id="fake-catalog-record",
                    content="FAKE catalog answer",
                ),
            ),
            digest="a" * 64,
            operator="fake-importer",
            occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )
    source = csv_text(
        valid_row(
            knowledge_id="fake-incoming-record",
            content="FAKE incoming answer",
        )
    )

    preview = asyncio.run(
        KnowledgeCatalogService(repository=repository).preview_csv(
            source,
            now=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )

    assert [
        issue.knowledge_id
        for issue in preview.issues
        if issue.code == "knowledge_conflict"
    ] == ["fake-incoming-record"]
