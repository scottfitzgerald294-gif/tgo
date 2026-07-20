"""Atomic JSON persistence for governed synthetic knowledge."""

import asyncio
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

from pydantic import ValidationError

from app.models import (
    KnowledgeActiveVersion,
    KnowledgeAuditEvent,
    KnowledgeCatalog,
    KnowledgeImportResult,
    KnowledgeRecord,
    KnowledgeRollbackResult,
)

KNOWLEDGE_SCHEMA_VERSION = 1


class KnowledgePersistenceError(RuntimeError):
    """Raised when the local catalog cannot be read or written safely."""


class DuplicateKnowledgeVersionError(ValueError):
    """Raised when an immutable knowledge version already exists."""


class KnowledgeVersionNotFoundError(LookupError):
    """Raised when rollback targets an unknown immutable version."""


class KnowledgeVersionAlreadyActiveError(ValueError):
    """Raised when rollback targets the current active version."""


@runtime_checkable
class KnowledgeRepository(Protocol):
    """Persistence boundary for local knowledge governance."""

    async def initialize(self) -> None: ...

    async def snapshot(self) -> KnowledgeCatalog: ...

    async def import_records(
        self,
        records: tuple[KnowledgeRecord, ...],
        *,
        digest: str,
        operator: str,
        occurred_at: datetime,
    ) -> KnowledgeImportResult: ...

    async def rollback(
        self,
        knowledge_id: str,
        *,
        to_version: int,
        operator: str,
        occurred_at: datetime,
    ) -> KnowledgeRollbackResult: ...


class JsonKnowledgeRepository:
    """Persist one small, single-process catalog as an atomic JSON snapshot."""

    def __init__(self, catalog_path: Path) -> None:
        self._catalog_path = catalog_path
        self._lock = threading.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def snapshot(self) -> KnowledgeCatalog:
        return await asyncio.to_thread(self._snapshot_sync)

    async def import_records(
        self,
        records: tuple[KnowledgeRecord, ...],
        *,
        digest: str,
        operator: str,
        occurred_at: datetime,
    ) -> KnowledgeImportResult:
        return await asyncio.to_thread(
            self._import_records_sync,
            records,
            digest,
            operator,
            occurred_at,
        )

    async def rollback(
        self,
        knowledge_id: str,
        *,
        to_version: int,
        operator: str,
        occurred_at: datetime,
    ) -> KnowledgeRollbackResult:
        return await asyncio.to_thread(
            self._rollback_sync,
            knowledge_id,
            to_version,
            operator,
            occurred_at,
        )

    def _initialize_sync(self) -> None:
        with self._lock:
            if self._catalog_path.exists():
                self._read_catalog()
                return
            try:
                self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise self._unavailable("initialize") from error
            self._write_catalog(KnowledgeCatalog())

    def _snapshot_sync(self) -> KnowledgeCatalog:
        with self._lock:
            return self._read_catalog()

    def _import_records_sync(
        self,
        records: tuple[KnowledgeRecord, ...],
        digest: str,
        operator: str,
        occurred_at: datetime,
    ) -> KnowledgeImportResult:
        with self._lock:
            catalog = self._read_catalog()
            existing_keys = {
                (record.knowledge_id, record.version) for record in catalog.records
            }
            incoming_keys: set[tuple[str, int]] = set()
            for record in records:
                key = (record.knowledge_id, record.version)
                if key in existing_keys or key in incoming_keys:
                    raise DuplicateKnowledgeVersionError(
                        "Knowledge id and version already exist"
                    )
                incoming_keys.add(key)

            active_by_id = {
                active.knowledge_id: active.version
                for active in catalog.active_versions
            }
            audit_events = list(catalog.audit_events)
            for record in sorted(
                records,
                key=lambda item: (item.knowledge_id, item.version),
            ):
                from_version = active_by_id.get(record.knowledge_id)
                active_by_id[record.knowledge_id] = record.version
                audit_events.append(
                    KnowledgeAuditEvent(
                        event_id=uuid4(),
                        event="knowledge_imported",
                        knowledge_id=record.knowledge_id,
                        from_version=from_version,
                        to_version=record.version,
                        operator=operator,
                        occurred_at=occurred_at,
                    )
                )

            updated = KnowledgeCatalog(
                records=tuple((*catalog.records, *records)),
                active_versions=tuple(
                    KnowledgeActiveVersion(
                        knowledge_id=knowledge_id,
                        version=version,
                    )
                    for knowledge_id, version in sorted(active_by_id.items())
                ),
                audit_events=tuple(audit_events),
            )
            self._write_catalog(updated)
            return KnowledgeImportResult(
                digest=digest,
                imported_count=len(records),
                active_count=len(updated.active_versions),
            )

    def _rollback_sync(
        self,
        knowledge_id: str,
        to_version: int,
        operator: str,
        occurred_at: datetime,
    ) -> KnowledgeRollbackResult:
        with self._lock:
            catalog = self._read_catalog()
            if not any(
                record.knowledge_id == knowledge_id and record.version == to_version
                for record in catalog.records
            ):
                raise KnowledgeVersionNotFoundError(
                    "Knowledge rollback target does not exist"
                )
            active_by_id = {
                active.knowledge_id: active.version
                for active in catalog.active_versions
            }
            from_version = active_by_id.get(knowledge_id)
            if from_version is None:
                raise KnowledgeVersionNotFoundError(
                    "Knowledge record has no active version"
                )
            if from_version == to_version:
                raise KnowledgeVersionAlreadyActiveError(
                    "Knowledge rollback target is already active"
                )

            active_by_id[knowledge_id] = to_version
            audit_event = KnowledgeAuditEvent(
                event_id=uuid4(),
                event="knowledge_rolled_back",
                knowledge_id=knowledge_id,
                from_version=from_version,
                to_version=to_version,
                operator=operator,
                occurred_at=occurred_at,
            )
            updated = KnowledgeCatalog(
                records=catalog.records,
                active_versions=tuple(
                    KnowledgeActiveVersion(
                        knowledge_id=active_id,
                        version=version,
                    )
                    for active_id, version in sorted(active_by_id.items())
                ),
                audit_events=tuple((*catalog.audit_events, audit_event)),
            )
            self._write_catalog(updated)
            return KnowledgeRollbackResult(
                knowledge_id=knowledge_id,
                from_version=from_version,
                to_version=to_version,
            )

    def _read_catalog(self) -> KnowledgeCatalog:
        try:
            catalog = KnowledgeCatalog.model_validate_json(
                self._catalog_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as error:
            raise self._unavailable("read") from error
        if catalog.schema_version != KNOWLEDGE_SCHEMA_VERSION:
            raise self._unavailable("validate schema")
        return catalog

    def _write_catalog(self, catalog: KnowledgeCatalog) -> None:
        temporary_path = self._catalog_path.with_name(f"{self._catalog_path.name}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    catalog.model_dump(mode="json"),
                    stream,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self._catalog_path)
        except OSError as error:
            raise self._unavailable("write") from error

    @staticmethod
    def _unavailable(operation: str) -> KnowledgePersistenceError:
        return KnowledgePersistenceError(
            f"Knowledge catalog persistence unavailable during {operation}"
        )
