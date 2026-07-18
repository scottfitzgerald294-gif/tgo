"""CSV preview and deterministic governance for synthetic knowledge."""

import csv
import hashlib
import io
from datetime import datetime
from itertools import combinations
from typing import Protocol

from pydantic import ValidationError

from app.models import (
    ApprovalStatus,
    ImportPreview,
    KnowledgeCatalog,
    KnowledgeImportResult,
    KnowledgeIssue,
    KnowledgeIssueSeverity,
    KnowledgeKind,
    KnowledgeRecord,
    KnowledgeRollbackResult,
    KnowledgeScope,
    KnowledgeStatus,
    RiskLevel,
)
from app.repositories import KnowledgeRepository

KNOWLEDGE_CSV_HEADERS = (
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


class KnowledgeSnapshotRepository(Protocol):
    """Read boundary required by a knowledge preview."""

    async def snapshot(self) -> KnowledgeCatalog: ...


class PreviewDigestMismatchError(ValueError):
    """Raised when formal import content differs from the reviewed preview."""


class KnowledgeImportBlockedError(ValueError):
    """Raised when a preview contains blocking errors or unsafe operator."""


class KnowledgeCatalogService:
    """Validate exact CSV content without hidden defaults or network calls."""

    def __init__(
        self,
        *,
        repository: KnowledgeSnapshotRepository | KnowledgeRepository,
    ) -> None:
        self._repository = repository

    async def preview_csv(
        self,
        csv_text: str,
        *,
        now: datetime,
    ) -> ImportPreview:
        digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        catalog = await self._repository.snapshot()
        reader = csv.DictReader(io.StringIO(csv_text, newline=""))
        if tuple(reader.fieldnames or ()) != KNOWLEDGE_CSV_HEADERS:
            issue = KnowledgeIssue(
                code="missing_header",
                severity=KnowledgeIssueSeverity.ERROR,
                row_number=None,
                knowledge_id=None,
                message="CSV headers must match the fixed knowledge contract",
            )
            return ImportPreview(
                digest=digest,
                issues=(issue,),
                error_count=1,
            )

        records: list[KnowledgeRecord] = []
        parsed_rows: list[tuple[int, KnowledgeRecord]] = []
        issues: list[KnowledgeIssue] = []
        seen_keys: set[tuple[str, int]] = set()
        catalog_keys = {
            (record.knowledge_id, record.version) for record in catalog.records
        }
        for row_number, row in enumerate(reader, start=2):
            knowledge_id = row.get("knowledge_id") or None
            allowed_value = row.get("allowed_for_auto_reply")
            if allowed_value == "true":
                allowed_for_auto_reply: bool | str | None = True
            elif allowed_value == "false":
                allowed_for_auto_reply = False
            else:
                allowed_for_auto_reply = allowed_value
            values: dict[str, object] = {
                **row,
                "allowed_for_auto_reply": allowed_for_auto_reply,
                "reviewed_by": row.get("reviewed_by") or None,
            }
            try:
                record = KnowledgeRecord.model_validate(values)
            except ValidationError:
                issues.append(
                    KnowledgeIssue(
                        code="row_validation_error",
                        severity=KnowledgeIssueSeverity.ERROR,
                        row_number=row_number,
                        knowledge_id=knowledge_id,
                        message="Knowledge row failed typed validation",
                    )
                )
                continue

            records.append(record)
            parsed_rows.append((row_number, record))
            key = (record.knowledge_id, record.version)
            if key in seen_keys:
                issues.append(
                    self._issue(
                        code="duplicate_in_batch",
                        severity=KnowledgeIssueSeverity.ERROR,
                        row_number=row_number,
                        knowledge_id=record.knowledge_id,
                    )
                )
            seen_keys.add(key)
            if key in catalog_keys:
                issues.append(
                    self._issue(
                        code="duplicate_in_catalog",
                        severity=KnowledgeIssueSeverity.ERROR,
                        row_number=row_number,
                        knowledge_id=record.knowledge_id,
                    )
                )
            if not record.source.casefold().startswith(("fake://", "test://")):
                issues.append(
                    self._issue(
                        code="invalid_source",
                        severity=KnowledgeIssueSeverity.ERROR,
                        row_number=row_number,
                        knowledge_id=record.knowledge_id,
                    )
                )
            if record.status is not KnowledgeStatus.PUBLISHED:
                issues.append(self._warning("not_published", row_number, record))
            if (
                record.approval_status is not ApprovalStatus.APPROVED
                or record.reviewed_by is None
            ):
                issues.append(self._warning("unreviewed", row_number, record))
            if record.expires_at <= now:
                issues.append(self._warning("expired", row_number, record))
            if record.effective_at > now:
                issues.append(self._warning("not_yet_effective", row_number, record))
            if record.risk_level is RiskLevel.HIGH:
                issues.append(self._warning("high_risk", row_number, record))
            if not record.allowed_for_auto_reply:
                issues.append(self._warning("auto_reply_disabled", row_number, record))
        conflicting_keys = self._conflicting_keys(
            self._candidate_active_records(catalog, tuple(records))
        )
        for row_number, record in parsed_rows:
            if (record.knowledge_id, record.version) in conflicting_keys:
                issues.append(self._warning("knowledge_conflict", row_number, record))
        return ImportPreview(
            digest=digest,
            records=tuple(records),
            issues=tuple(issues),
            error_count=sum(
                issue.severity is KnowledgeIssueSeverity.ERROR for issue in issues
            ),
            warning_count=sum(
                issue.severity is KnowledgeIssueSeverity.WARNING for issue in issues
            ),
        )

    @staticmethod
    def _candidate_active_records(
        catalog: KnowledgeCatalog,
        incoming_records: tuple[KnowledgeRecord, ...],
    ) -> tuple[KnowledgeRecord, ...]:
        records_by_key = {
            (record.knowledge_id, record.version): record for record in catalog.records
        }
        active_by_id = {
            active.knowledge_id: records_by_key[(active.knowledge_id, active.version)]
            for active in catalog.active_versions
            if (active.knowledge_id, active.version) in records_by_key
        }
        for record in sorted(
            incoming_records,
            key=lambda item: (item.knowledge_id, item.version),
        ):
            active_by_id[record.knowledge_id] = record
        return tuple(active_by_id.values())

    async def import_csv(
        self,
        csv_text: str,
        *,
        expected_digest: str,
        operator: str,
        now: datetime,
    ) -> KnowledgeImportResult:
        preview = await self.preview_csv(csv_text, now=now)
        if preview.digest != expected_digest:
            raise PreviewDigestMismatchError(
                "Knowledge CSV does not match the reviewed preview"
            )
        normalized_operator = operator.strip()
        if not normalized_operator.casefold().startswith(("fake-", "test-")):
            raise KnowledgeImportBlockedError(
                "Knowledge operator must be an explicit FAKE or TEST identity"
            )
        if preview.error_count:
            raise KnowledgeImportBlockedError(
                "Knowledge CSV contains blocking preview errors"
            )
        repository = self._repository
        if not isinstance(repository, KnowledgeRepository):
            raise KnowledgeImportBlockedError(
                "Knowledge repository does not support formal import"
            )
        return await repository.import_records(
            preview.records,
            digest=preview.digest,
            operator=normalized_operator,
            occurred_at=now,
        )

    async def eligible_records(
        self,
        scope: KnowledgeScope,
        *,
        now: datetime,
    ) -> tuple[KnowledgeRecord, ...]:
        catalog = await self._repository.snapshot()
        active_keys = {
            (active.knowledge_id, active.version) for active in catalog.active_versions
        }
        active_records = tuple(
            record
            for record in catalog.records
            if (record.knowledge_id, record.version) in active_keys
        )
        conflicting_keys = self._conflicting_keys(active_records)
        return tuple(
            record
            for record in active_records
            if (record.knowledge_id, record.version) not in conflicting_keys
            and self._matches_scope(record, scope)
            and self._is_statically_eligible(record, now)
        )

    async def rollback(
        self,
        knowledge_id: str,
        *,
        to_version: int,
        operator: str,
        now: datetime,
    ) -> KnowledgeRollbackResult:
        normalized_operator = operator.strip()
        if not normalized_operator.casefold().startswith(("fake-", "test-")):
            raise KnowledgeImportBlockedError(
                "Knowledge operator must be an explicit FAKE or TEST identity"
            )
        repository = self._repository
        if not isinstance(repository, KnowledgeRepository):
            raise KnowledgeImportBlockedError(
                "Knowledge repository does not support rollback"
            )
        return await repository.rollback(
            knowledge_id,
            to_version=to_version,
            operator=normalized_operator,
            occurred_at=now,
        )

    @classmethod
    def _conflicting_keys(
        cls,
        records: tuple[KnowledgeRecord, ...],
    ) -> set[tuple[str, int]]:
        conflicts: set[tuple[str, int]] = set()
        for first, second in combinations(records, 2):
            if cls._records_conflict(first, second):
                conflicts.add((first.knowledge_id, first.version))
                conflicts.add((second.knowledge_id, second.version))
        return conflicts

    @staticmethod
    def _records_conflict(
        first: KnowledgeRecord,
        second: KnowledgeRecord,
    ) -> bool:
        scope_pairs = (
            (first.applicable_shop, second.applicable_shop),
            (first.applicable_product, second.applicable_product),
            (first.applicable_sku, second.applicable_sku),
        )
        return (
            first.kind is second.kind
            and " ".join(first.content.split()).casefold()
            != " ".join(second.content.split()).casefold()
            and all(
                first_value == second_value or "*" in {first_value, second_value}
                for first_value, second_value in scope_pairs
            )
            and first.effective_at < second.expires_at
            and second.effective_at < first.expires_at
            and first.status is KnowledgeStatus.PUBLISHED
            and second.status is KnowledgeStatus.PUBLISHED
            and first.approval_status is ApprovalStatus.APPROVED
            and second.approval_status is ApprovalStatus.APPROVED
        )

    @staticmethod
    def _matches_scope(record: KnowledgeRecord, scope: KnowledgeScope) -> bool:
        return (
            record.applicable_shop in {"*", scope.shop_id}
            and record.applicable_product in {"*", scope.product_id}
            and record.applicable_sku in {"*", scope.sku_id}
        )

    @staticmethod
    def _is_statically_eligible(
        record: KnowledgeRecord,
        now: datetime,
    ) -> bool:
        return (
            record.status is KnowledgeStatus.PUBLISHED
            and record.approval_status is ApprovalStatus.APPROVED
            and record.reviewed_by is not None
            and record.source.casefold().startswith(("fake://", "test://"))
            and record.effective_at <= now < record.expires_at
            and record.risk_level is not RiskLevel.HIGH
            and record.allowed_for_auto_reply
            and record.kind
            not in {
                KnowledgeKind.FORBIDDEN_ANSWER,
                KnowledgeKind.HANDOFF_CONDITION,
            }
        )

    @staticmethod
    def _issue(
        *,
        code: str,
        severity: KnowledgeIssueSeverity,
        row_number: int,
        knowledge_id: str,
    ) -> KnowledgeIssue:
        return KnowledgeIssue(
            code=code,
            severity=severity,
            row_number=row_number,
            knowledge_id=knowledge_id,
            message=f"Knowledge preview issue: {code}",
        )

    @classmethod
    def _warning(
        cls,
        code: str,
        row_number: int,
        record: KnowledgeRecord,
    ) -> KnowledgeIssue:
        return cls._issue(
            code=code,
            severity=KnowledgeIssueSeverity.WARNING,
            row_number=row_number,
            knowledge_id=record.knowledge_id,
        )
