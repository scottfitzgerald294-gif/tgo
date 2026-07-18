"""Typed models for governed synthetic knowledge."""

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.models.messages import Identifier

KnowledgeTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
KnowledgeContent = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=8000),
]


class KnowledgeKind(StrEnum):
    """Supported first-version knowledge categories."""

    PRODUCT = "product"
    SKU = "sku"
    FAQ = "faq"
    SHIPPING = "shipping"
    AFTER_SALES = "after_sales"
    FORBIDDEN_ANSWER = "forbidden_answer"
    HANDOFF_CONDITION = "handoff_condition"


class KnowledgeStatus(StrEnum):
    """Lifecycle status of one immutable knowledge version."""

    DRAFT = "draft"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


class ApprovalStatus(StrEnum):
    """Review decision attached to one knowledge version."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RiskLevel(StrEnum):
    """Static risk classification used by deterministic eligibility checks."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class KnowledgeIssueSeverity(StrEnum):
    """Whether a preview issue blocks formal import."""

    ERROR = "error"
    WARNING = "warning"


class KnowledgeRecord(BaseModel):
    """One immutable, governed synthetic knowledge version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_id: Identifier
    version: int = Field(ge=1)
    kind: KnowledgeKind
    title: KnowledgeTitle
    content: KnowledgeContent
    status: KnowledgeStatus
    approval_status: ApprovalStatus
    applicable_shop: Identifier
    applicable_product: Identifier
    applicable_sku: Identifier
    source: str = Field(max_length=512)
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    risk_level: RiskLevel
    allowed_for_auto_reply: bool
    reviewed_by: Identifier | None

    @model_validator(mode="after")
    def validate_governance(self) -> Self:
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be later than effective_at")
        if self.approval_status is ApprovalStatus.APPROVED and self.reviewed_by is None:
            raise ValueError("approved knowledge requires reviewed_by")
        return self


class KnowledgeIssue(BaseModel):
    """One safe CSV preview issue without row content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: KnowledgeIssueSeverity
    row_number: int | None
    knowledge_id: Identifier | None
    message: str


class KnowledgeActiveVersion(BaseModel):
    """Current immutable version selected for one knowledge id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_id: Identifier
    version: int = Field(ge=1)


class KnowledgeAuditEvent(BaseModel):
    """Body-free import or rollback audit event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    event: str
    knowledge_id: Identifier
    from_version: int | None = Field(default=None, ge=1)
    to_version: int = Field(ge=1)
    operator: Identifier
    occurred_at: AwareDatetime


class KnowledgeCatalog(BaseModel):
    """Versioned local catalog persisted as one JSON snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    records: tuple[KnowledgeRecord, ...] = ()
    active_versions: tuple[KnowledgeActiveVersion, ...] = ()
    audit_events: tuple[KnowledgeAuditEvent, ...] = ()


class ImportPreview(BaseModel):
    """Read-only result of validating exact CSV bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    digest: str
    records: tuple[KnowledgeRecord, ...] = ()
    issues: tuple[KnowledgeIssue, ...] = ()
    error_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)


class KnowledgeScope(BaseModel):
    """Concrete shop/product/SKU query scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shop_id: Identifier
    product_id: Identifier
    sku_id: Identifier


class KnowledgeImportResult(BaseModel):
    """Counts from one atomic formal import."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    digest: str
    imported_count: int = Field(ge=0)
    active_count: int = Field(ge=0)


class KnowledgeRollbackResult(BaseModel):
    """Result of moving one active-version pointer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_id: Identifier
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
