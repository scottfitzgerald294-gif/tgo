"""Unit tests for the atomic local JSON knowledge catalog."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.repositories import (
    DuplicateKnowledgeVersionError,
    JsonKnowledgeRepository,
    KnowledgePersistenceError,
    KnowledgeVersionAlreadyActiveError,
    KnowledgeVersionNotFoundError,
)
from tests.fixtures.knowledge import knowledge_record


@pytest.mark.unit
def test_json_repository_initializes_imports_and_reopens_versions(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "pdd-knowledge.json"
    repository = JsonKnowledgeRepository(catalog_path)

    assert catalog_path.exists() is False

    asyncio.run(repository.initialize())
    result = asyncio.run(
        repository.import_records(
            (
                knowledge_record(version=1, content="FAKE v1"),
                knowledge_record(version=2, content="FAKE v2"),
            ),
            digest="a" * 64,
            operator="fake-importer",
            occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )
    reopened = JsonKnowledgeRepository(catalog_path)
    asyncio.run(reopened.initialize())
    snapshot = asyncio.run(reopened.snapshot())

    assert result.imported_count == 2
    assert result.active_count == 1
    assert len(snapshot.records) == 2
    assert snapshot.active_versions[0].knowledge_id == "fake-knowledge-001"
    assert snapshot.active_versions[0].version == 2
    assert all(event.event == "knowledge_imported" for event in snapshot.audit_events)


@pytest.mark.unit
def test_json_repository_rejects_duplicate_batch_atomically(
    tmp_path: Path,
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    record = knowledge_record()
    asyncio.run(
        repository.import_records(
            (record,),
            digest="a" * 64,
            operator="fake-importer",
            occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )
    before = asyncio.run(repository.snapshot())

    with pytest.raises(DuplicateKnowledgeVersionError):
        asyncio.run(
            repository.import_records(
                (
                    knowledge_record(
                        knowledge_id="fake-new",
                        content="FAKE new",
                    ),
                    record,
                ),
                digest="b" * 64,
                operator="fake-importer",
                occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
            )
        )

    assert asyncio.run(repository.snapshot()) == before


@pytest.mark.unit
@pytest.mark.parametrize(
    "contents",
    [
        "{not-json",
        '{"schema_version":99,"records":[],"active_versions":[],"audit_events":[]}',
    ],
)
def test_json_repository_preserves_invalid_catalog_for_diagnosis(
    tmp_path: Path,
    contents: str,
) -> None:
    catalog_path = tmp_path / "pdd-knowledge.json"
    catalog_path.write_text(contents, encoding="utf-8")
    repository = JsonKnowledgeRepository(catalog_path)

    with pytest.raises(KnowledgePersistenceError) as captured:
        asyncio.run(repository.initialize())

    assert catalog_path.read_text(encoding="utf-8") == contents
    assert str(catalog_path) not in str(captured.value)
    assert "not-json" not in str(captured.value)


@pytest.mark.unit
def test_json_repository_rolls_back_active_pointer_without_deleting_history(
    tmp_path: Path,
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    asyncio.run(
        repository.import_records(
            (
                knowledge_record(version=1, content="FAKE v1"),
                knowledge_record(version=2, content="FAKE v2"),
            ),
            digest="a" * 64,
            operator="fake-importer",
            occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )

    result = asyncio.run(
        repository.rollback(
            "fake-knowledge-001",
            to_version=1,
            operator="fake-operator",
            occurred_at=datetime(2026, 7, 19, tzinfo=UTC),
        )
    )
    snapshot = asyncio.run(repository.snapshot())

    assert (result.from_version, result.to_version) == (2, 1)
    assert len(snapshot.records) == 2
    assert snapshot.active_versions[0].version == 1
    assert snapshot.audit_events[-1].event == "knowledge_rolled_back"
    assert snapshot.audit_events[-1].from_version == 2
    assert snapshot.audit_events[-1].to_version == 1
    assert snapshot.audit_events[-1].operator == "fake-operator"
    assert "content" not in snapshot.audit_events[-1].model_dump()


@pytest.mark.unit
def test_json_repository_rejects_invalid_rollback_atomically(
    tmp_path: Path,
) -> None:
    repository = JsonKnowledgeRepository(tmp_path / "pdd-knowledge.json")
    asyncio.run(repository.initialize())
    asyncio.run(
        repository.import_records(
            (knowledge_record(),),
            digest="a" * 64,
            operator="fake-importer",
            occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )
    before = asyncio.run(repository.snapshot())

    with pytest.raises(KnowledgeVersionNotFoundError):
        asyncio.run(
            repository.rollback(
                "fake-knowledge-001",
                to_version=99,
                operator="fake-operator",
                occurred_at=datetime(2026, 7, 19, tzinfo=UTC),
            )
        )
    assert asyncio.run(repository.snapshot()) == before

    with pytest.raises(KnowledgeVersionAlreadyActiveError):
        asyncio.run(
            repository.rollback(
                "fake-knowledge-001",
                to_version=1,
                operator="fake-operator",
                occurred_at=datetime(2026, 7, 19, tzinfo=UTC),
            )
        )
    assert asyncio.run(repository.snapshot()) == before
