"""Integration tests for the local synthetic knowledge CLI."""

import asyncio
import csv
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from app.repositories import JsonKnowledgeRepository
from scripts.knowledge_catalog import main
from tests.fixtures.knowledge import KNOWLEDGE_HEADERS, csv_text, valid_row

REPOSITORY_ROOT = Path(__file__).parents[4]
EXTENSION_ROOT = Path(__file__).parents[2]


@pytest.mark.integration
def test_knowledge_cli_preview_outputs_only_safe_governance_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "pdd-knowledge.json"
    csv_path = tmp_path / "fake-knowledge.csv"
    source = csv_text(valid_row(content="FAKE secret-like body must stay hidden"))
    csv_path.write_text(source, encoding="utf-8")

    exit_code = main(
        [
            "--catalog",
            str(catalog_path),
            "preview",
            "--csv",
            str(csv_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "digest=" in output
    assert "records=1" in output
    assert "errors=0" in output
    assert "record=fake-knowledge-001@1" in output
    assert "FAKE secret-like body must stay hidden" not in output
    assert str(catalog_path) not in output
    assert str(csv_path) not in output


@pytest.mark.integration
def test_knowledge_cli_supports_direct_script_execution(tmp_path: Path) -> None:
    catalog_path = tmp_path / "pdd-knowledge.json"
    csv_path = tmp_path / "fake-knowledge.csv"
    csv_path.write_text(csv_text(valid_row()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/knowledge_catalog.py",
            "--catalog",
            str(catalog_path),
            "preview",
            "--csv",
            str(csv_path),
        ],
        cwd=EXTENSION_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "records=1" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr


@pytest.mark.integration
def test_knowledge_cli_import_requires_reviewed_digest_and_is_atomic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "pdd-knowledge.json"
    csv_path = tmp_path / "fake-knowledge.csv"
    source = csv_text(valid_row())
    csv_path.write_text(source, encoding="utf-8")

    rejected_exit = main(
        [
            "--catalog",
            str(catalog_path),
            "import",
            "--csv",
            str(csv_path),
            "--expected-digest",
            "0" * 64,
            "--operator",
            "fake-importer",
        ]
    )
    rejected_output = capsys.readouterr().out
    repository = JsonKnowledgeRepository(catalog_path)
    rejected_snapshot = asyncio.run(repository.snapshot())

    assert rejected_exit == 2
    assert rejected_snapshot.records == ()
    assert "error=preview_digest_mismatch" in rejected_output

    accepted_exit = main(
        [
            "--catalog",
            str(catalog_path),
            "import",
            "--csv",
            str(csv_path),
            "--expected-digest",
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "--operator",
            "fake-importer",
        ]
    )
    accepted_output = capsys.readouterr().out

    assert accepted_exit == 0
    assert "imported=1" in accepted_output
    assert "active=1" in accepted_output
    assert valid_row()["content"] not in accepted_output
    assert str(catalog_path) not in accepted_output


@pytest.mark.integration
def test_knowledge_cli_eligible_and_rollback_use_active_version_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "pdd-knowledge.json"
    csv_path = tmp_path / "fake-versions.csv"
    source = csv_text(
        valid_row(
            version="1",
            content="FAKE eligible version",
        ),
        valid_row(
            version="2",
            content="FAKE disabled version",
            allowed_for_auto_reply="false",
        ),
    )
    csv_path.write_text(source, encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert (
        main(
            [
                "--catalog",
                str(catalog_path),
                "import",
                "--csv",
                str(csv_path),
                "--expected-digest",
                digest,
                "--operator",
                "test-importer",
            ]
        )
        == 0
    )
    capsys.readouterr()

    before_exit = main(
        [
            "--catalog",
            str(catalog_path),
            "eligible",
            "--shop",
            "fake-shop",
            "--product",
            "fake-product",
            "--sku",
            "fake-sku",
        ]
    )
    before_output = capsys.readouterr().out
    rollback_exit = main(
        [
            "--catalog",
            str(catalog_path),
            "rollback",
            "--knowledge-id",
            "fake-knowledge-001",
            "--to-version",
            "1",
            "--operator",
            "test-operator",
        ]
    )
    rollback_output = capsys.readouterr().out
    after_exit = main(
        [
            "--catalog",
            str(catalog_path),
            "eligible",
            "--shop",
            "fake-shop",
            "--product",
            "fake-product",
            "--sku",
            "fake-sku",
        ]
    )
    after_output = capsys.readouterr().out

    assert before_exit == 0
    assert "eligible=0" in before_output
    assert rollback_exit == 0
    assert "rollback=fake-knowledge-001:2->1" in rollback_output
    assert after_exit == 0
    assert "eligible=1" in after_output
    assert "record=fake-knowledge-001@1" in after_output
    assert "FAKE eligible version" not in after_output


@pytest.mark.integration
def test_tracked_knowledge_csv_assets_are_fixed_and_obviously_synthetic() -> None:
    template_path = (
        REPOSITORY_ROOT / "knowledge" / "pdd" / "knowledge-import-template.csv"
    )
    example_path = REPOSITORY_ROOT / "knowledge" / "pdd" / "fake-knowledge.csv"

    with template_path.open(encoding="utf-8", newline="") as stream:
        template = csv.DictReader(stream)
        assert tuple(template.fieldnames or ()) == KNOWLEDGE_HEADERS
        assert list(template) == []

    with example_path.open(encoding="utf-8", newline="") as stream:
        example = csv.DictReader(stream)
        rows = list(example)

    assert tuple(example.fieldnames or ()) == KNOWLEDGE_HEADERS
    assert {row["kind"] for row in rows} == {
        "product",
        "sku",
        "faq",
        "shipping",
        "after_sales",
        "forbidden_answer",
        "handoff_condition",
    }
    assert all(row["knowledge_id"].startswith(("fake-", "test-")) for row in rows)
    assert all(
        row["source"].casefold().startswith(("fake://", "test://")) for row in rows
    )
    assert {
        row["allowed_for_auto_reply"]
        for row in rows
        if row["kind"] in {"forbidden_answer", "handoff_condition"}
    } == {"false"}
    assert {
        row["version"] for row in rows if row["knowledge_id"] == "fake-product-001"
    } == {"1", "2"}
