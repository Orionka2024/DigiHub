from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Literal


class FilingState(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    FROZEN = "frozen"
    VALIDATED = "validated"


@dataclass(frozen=True)
class Dimension:
    axis: str
    member: str


@dataclass(frozen=True)
class Context:
    id: str
    entity_scheme: str
    entity_identifier: str
    instant: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    dimensions: tuple[Dimension, ...] = ()

    def __post_init__(self) -> None:
        if not ((self.instant is not None and self.start_date is None and self.end_date is None) or
                (self.instant is None and self.start_date is not None and self.end_date is not None)):
            raise ValueError("Context must have either an instant or start/end dates.")
        if self.start_date and self.start_date >= self.end_date:
            raise ValueError("Duration context start must precede end.")


@dataclass(frozen=True)
class Unit:
    id: str
    measure: str


@dataclass(frozen=True)
class SourceRef:
    document_sha256: str
    location: str
    extracted_value: str
    reviewer: str | None = None


@dataclass(frozen=True)
class Fact:
    id: str
    qname: str
    context_id: str
    value: Decimal | str | bool | date | None
    kind: Literal["numeric", "text", "boolean", "date"]
    source: SourceRef
    unit_id: str | None = None
    decimals: int | None = None
    nil: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {"numeric", "text", "boolean", "date"}:
            raise ValueError("Unknown fact kind.")
        if not self.nil:
            valid = {"numeric": isinstance(self.value, Decimal) and self.value.is_finite() if isinstance(self.value, Decimal) else False,
                     "text": isinstance(self.value, str), "boolean": type(self.value) is bool,
                     "date": type(self.value) is date}
            if not valid[self.kind]:
                raise ValueError(f"Invalid {self.kind} fact value.")
        if self.nil and self.value is not None:
            raise ValueError("Nil facts cannot carry a value.")
        if self.kind == "numeric" and (not self.unit_id or self.decimals is None):
            raise ValueError("Numeric facts require unit_id and decimals.")
        if self.kind != "numeric" and self.unit_id:
            raise ValueError("Only numeric facts may have a unit.")


@dataclass
class FilingSnapshot:
    filing_id: str
    entity_name: str
    kvk_number: str
    period_start: date
    period_end: date
    taxonomy_id: str
    entry_point_key: str
    document_sha256: str
    report_sections: set[str] = field(default_factory=set)
    reviewed_requirement_ids: set[str] = field(default_factory=set)
    facts: list[Fact] = field(default_factory=list)
    contexts: list[Context] = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)
    state: FilingState = FilingState.DRAFT
    frozen_at: datetime | None = None
    validation_digest: str | None = None
    frozen_digest: str | None = None
    is_final: bool = False
    signatory_name: str | None = None
    approval_date: date | None = None


    def __post_init__(self) -> None:
        if not self.kvk_number.isdigit() or len(self.kvk_number) != 8 or self.kvk_number.startswith("00"):
            raise ValueError("KVK number must be exactly eight digits and must not start with 00.")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.document_sha256):
            raise ValueError("A SHA-256 source-document hash is required.")
        if self.period_start >= self.period_end:
            raise ValueError("Reporting period is invalid.")

    def freeze(self, is_final: bool = False, signatory_name: str | None = None, approval_date: date | None = None) -> None:
        if self.state not in (FilingState.DRAFT, FilingState.REVIEWED):
            raise ValueError(f"Cannot freeze a filing in state {self.state}.")
        self.state = FilingState.FROZEN
        self.frozen_at = datetime.now(timezone.utc)
        self.is_final = is_final
        self.signatory_name = signatory_name
        self.approval_date = approval_date
        self.frozen_digest = self.content_digest()

    def content_digest(self) -> str:
        data = asdict(self)
        for key in ("state", "frozen_at", "frozen_digest", "validation_digest"):
            data.pop(key)
        def encode(value):
            if isinstance(value, set):
                return sorted(value)
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            if isinstance(value, Decimal):
                return str(value)
            raise TypeError(type(value).__name__)
        return sha256(json.dumps(data, default=encode, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def verify_frozen(self) -> None:
        if not self.frozen_digest or self.frozen_digest != self.content_digest():
            raise ValueError("Frozen filing content has changed; review and freeze it again.")

    def mark_validated(self, report: str) -> None:
        if self.state != FilingState.FROZEN:
            raise ValueError("Only a frozen filing can become validated.")
        self.verify_frozen()
        self.validation_digest = sha256(report.encode("utf-8")).hexdigest()
        self.state = FilingState.VALIDATED
