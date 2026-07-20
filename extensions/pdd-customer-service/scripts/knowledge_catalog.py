"""Safe local CLI for governed synthetic knowledge."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="Ignored local JSON catalog path",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview", help="Preview a synthetic CSV")
    preview.add_argument("--csv", type=Path, required=True)
    formal_import = commands.add_parser(
        "import",
        help="Import an exactly reviewed synthetic CSV",
    )
    formal_import.add_argument("--csv", type=Path, required=True)
    formal_import.add_argument("--expected-digest", required=True)
    formal_import.add_argument("--operator", required=True)
    eligible = commands.add_parser(
        "eligible",
        help="List eligible active synthetic records",
    )
    eligible.add_argument("--shop", required=True)
    eligible.add_argument("--product", required=True)
    eligible.add_argument("--sku", required=True)
    rollback = commands.add_parser(
        "rollback",
        help="Move an active pointer to an immutable earlier version",
    )
    rollback.add_argument("--knowledge-id", required=True)
    rollback.add_argument("--to-version", type=int, required=True)
    rollback.add_argument("--operator", required=True)
    return parser


async def _run(args: argparse.Namespace) -> int:
    from app.models import KnowledgeScope
    from app.repositories import JsonKnowledgeRepository
    from app.services import KnowledgeCatalogService

    repository = JsonKnowledgeRepository(args.catalog)
    await repository.initialize()
    service = KnowledgeCatalogService(repository=repository)
    if args.command == "preview":
        source = args.csv.read_text(encoding="utf-8")
        preview = await service.preview_csv(source, now=datetime.now(UTC))
        print(f"digest={preview.digest}")
        print(f"records={len(preview.records)}")
        print(f"errors={preview.error_count}")
        print(f"warnings={preview.warning_count}")
        for record in preview.records:
            print(f"record={record.knowledge_id}@{record.version}")
        for issue in preview.issues:
            print(
                f"issue={issue.severity.value}:{issue.code}:{issue.knowledge_id or '-'}"
            )
        return 0 if preview.error_count == 0 else 2
    if args.command == "import":
        source = args.csv.read_text(encoding="utf-8")
        import_result = await service.import_csv(
            source,
            expected_digest=args.expected_digest,
            operator=args.operator,
            now=datetime.now(UTC),
        )
        print(f"digest={import_result.digest}")
        print(f"imported={import_result.imported_count}")
        print(f"active={import_result.active_count}")
        return 0
    if args.command == "eligible":
        records = await service.eligible_records(
            KnowledgeScope(
                shop_id=args.shop,
                product_id=args.product,
                sku_id=args.sku,
            ),
            now=datetime.now(UTC),
        )
        print(f"eligible={len(records)}")
        for record in records:
            print(f"record={record.knowledge_id}@{record.version}")
        return 0
    if args.command == "rollback":
        rollback_result = await service.rollback(
            args.knowledge_id,
            to_version=args.to_version,
            operator=args.operator,
            now=datetime.now(UTC),
        )
        print(
            f"rollback={rollback_result.knowledge_id}:"
            f"{rollback_result.from_version}->{rollback_result.to_version}"
        )
        return 0
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run one local knowledge operation without network access."""

    from app.repositories import (
        KnowledgePersistenceError,
        KnowledgeVersionAlreadyActiveError,
        KnowledgeVersionNotFoundError,
    )
    from app.services import (
        KnowledgeImportBlockedError,
        PreviewDigestMismatchError,
    )

    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except PreviewDigestMismatchError:
        print("error=preview_digest_mismatch")
    except KnowledgeImportBlockedError:
        print("error=knowledge_import_blocked")
    except (
        KnowledgePersistenceError,
        KnowledgeVersionAlreadyActiveError,
        KnowledgeVersionNotFoundError,
        OSError,
        UnicodeError,
    ):
        print("error=knowledge_operation_failed")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
