"""Pydantic request/response models for the KVK_v2 API.

These are deliberately separate from the core dataclasses in models.py so that
the API surface can evolve independently of the domain model.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Taxonomy ──────────────────────────────────────────────────────────────────

class TaxonomyRequirementIn(BaseModel):
    id: str
    qname: str | None = None
    section: str | None = None
    conditional: bool = False


class TaxonomyReleaseIn(BaseModel):
    id: str
    status: str = "final"
    entry_points: dict[str, str]
    namespaces: dict[str, str]
    sha256: str
    requirements: list[TaxonomyRequirementIn] = []


class EntryPointMetaOut(BaseModel):
    key: str
    file: str
    name: str
    company_class: str
    framework: str
    sector: str
    consolidation: str
    domain: str


class EnrichedTaxonomyReleaseOut(BaseModel):
    id: str
    status: str
    version: str
    name: str
    authority: str
    publication_date: str
    reporting_year: int
    reporting_date: str
    sha256: str
    package_verified: bool
    is_active: bool
    entry_point_count: int
    concept_count: int


class ConceptMetadataOut(BaseModel):
    qname: str
    namespace: str
    local_name: str
    label_nl: str
    label_en: str
    documentation: str
    data_type: str
    period_type: str
    balance: str | None
    abstract: bool
    nillable: bool
    mandatory_status: str
    rule_ids: list[str]
    condition_nl: str


class ValidationRuleOut(BaseModel):
    rule_id: str
    rule_type: str
    status: str
    concept_qname: str | None
    condition_nl: str
    error_message_nl: str
    entry_points: list[str]


class ChecklistItemOut(BaseModel):
    concept_qname: str
    label_nl: str
    label_en: str
    data_type: str
    period_type: str
    balance: str | None
    status: str
    condition_nl: str
    rule_ids: list[str]
    is_satisfied: bool
    fact_value: str | None


class ChecklistSectionOut(BaseModel):
    section_id: str
    title_nl: str
    title_en: str
    items: list[ChecklistItemOut]
    total: int
    satisfied: int
    mandatory_count: int
    conditional_count: int


class SelectEntryPointOut(BaseModel):
    entry_point_key: str | None


# ── Extracted Document ─────────────────────────────────────────────────────────

class RunOut(BaseModel):
    text: str
    bold: bool
    italic: bool


class SourceNodeOut(BaseModel):
    id: str
    kind: Literal["paragraph", "table"]
    location: str
    style: str | None
    text: str = ""
    runs: list[RunOut] = []
    rows: list[list[str]] = []


class ExtractedDocumentOut(BaseModel):
    sha256: str
    nodes: list[SourceNodeOut]
    headers: list[str]
    footers: list[str]
    warnings: list[str]


# ── Snapshot creation ──────────────────────────────────────────────────────────

class SnapshotCreateIn(BaseModel):
    entity_name: str
    kvk_number: str
    period_start: date
    period_end: date
    taxonomy_id: str
    entry_point_key: str
    document_sha256: str


class SnapshotOut(BaseModel):
    filing_id: str
    entity_name: str
    kvk_number: str
    period_start: date
    period_end: date
    taxonomy_id: str
    entry_point_key: str
    document_sha256: str
    state: str
    fact_count: int
    context_count: int
    unit_count: int
    report_sections: list[str]
    reviewed_requirement_ids: list[str]
    warnings: list[str] = []
    facts: list[dict] = []
    contexts: list[dict] = []
    units: list[dict] = []
    document: ExtractedDocumentOut | None = None
    is_final: bool = False
    signatory_name: str | None = None
    approval_date: date | None = None


class FreezeIn(BaseModel):
    is_final: bool = False
    signatory_name: str | None = None
    approval_date: date | None = None

# ── Mapping ────────────────────────────────────────────────────────────────────

class MappingDecisionIn(BaseModel):
    source_node_id: str
    source_location: str
    qname: str
    context_id: str
    kind: Literal["numeric", "text", "boolean", "date"]
    value: Any  # Decimal | str | bool | None
    unit_id: str | None = None
    decimals: int | None = None
    reviewer: str


class DimensionIn(BaseModel):
    axis: str
    member: str


class ContextIn(BaseModel):
    id: str
    entity_scheme: str
    entity_identifier: str
    instant: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    dimensions: list[DimensionIn] = []


class UnitIn(BaseModel):
    id: str
    measure: str


class MapFactIn(BaseModel):
    replaces_fact_id: str | None = None
    decision: MappingDecisionIn
    context: ContextIn | None = None  # Provide to auto-register context
    unit: UnitIn | None = None        # Provide to auto-register unit


class MapFactOut(BaseModel):
    fact_id: str
    qname: str
    status: str = "mapped"


# ── Sections / Requirements ────────────────────────────────────────────────────

class AddSectionIn(BaseModel):
    section: str


class ReviewRequirementIn(BaseModel):
    requirement_id: str


# ── Auto-Tagger ────────────────────────────────────────────────────────────────

class AutoTagRequest(BaseModel):
    source_node_id: str


class AutoTagRecommendation(BaseModel):
    source_node_id: str
    source_location: str
    row_index: int
    col_index: int
    qname: str
    value: str
    kind: str
    label: str = ""
    source_label: str = ""
    source_text: str = ""
    period_type: str = ""
    year_hint: int | None = None
    match_score: float = 0
    alternatives: list[str] = Field(default_factory=list)


class AutoTagResponse(BaseModel):
    recommendations: list[AutoTagRecommendation]


# ── Validation ─────────────────────────────────────────────────────────────────

class ValidationIssueOut(BaseModel):
    code: str
    message: str
    severity: str = "error"
    concept: str | None = None
    rule_ref: str | None = None


class ValidateOut(BaseModel):
    ok: bool
    issues: list[ValidationIssueOut]


# ── KVK Lookup ────────────────────────────────────────────────────────────────

class KvkLookupOut(BaseModel):
    found: bool
    kvk_number: str | None = None
    entity_name: str | None = None
    source: str | None = None
    error: str | None = None


# ── Workspace save/load ───────────────────────────────────────────────────────

class WorkspaceSaveIn(BaseModel):
    kvk_number: str
    filing_id: str


class WorkspaceOut(BaseModel):
    kvk_number: str
    filing_id: str
    saved_at: str
