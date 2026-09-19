"""Local filing checks used before independent validation.

Checks identity, provenance metadata, references, basic concept types, periods,
units, available calculation arcs and reviewed presence requirements. This is
not a complete XBRL/DTS, dimensions, XPath/formula or KVK filing-rule processor.
FilingService additionally requires an independent validator before export.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from KVK_v2.registry import TaxonomyRelease, EnrichedTaxonomyRelease

from KVK_v2.models import Context, Fact, FilingSnapshot, Unit


@dataclass
class ValidationIssue:
    code: str
    message: str
    concept: str | None = None
    severity: str = "error"   # "error" | "warning" | "info"
    rule_ref: str | None = None

    def __str__(self) -> str:
        parts = [f"[{self.severity.upper()}] {self.code}: {self.message}"]
        if self.concept:
            parts.append(f"  Concept: {self.concept}")
        if self.rule_ref:
            parts.append(f"  Rule: {self.rule_ref}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def validate_snapshot(
    snapshot: FilingSnapshot,
    taxonomy: "TaxonomyRelease | EnrichedTaxonomyRelease",
) -> list[ValidationIssue]:
    """Run all validation checks on a FilingSnapshot.

    Returns a (possibly empty) list of ValidationIssue objects.
    """
    issues: list[ValidationIssue] = []
    try:
        taxonomy.entry_point(snapshot.entry_point_key)
    except ValueError as exc:
        issues.append(ValidationIssue("TAXONOMY-001", str(exc)))
    if snapshot.taxonomy_id != taxonomy.id:
        issues.append(ValidationIssue("TAXONOMY-002", "Snapshot taxonomy identity does not match."))
    for fact in snapshot.facts:
        if fact.source.document_sha256 != snapshot.document_sha256:
            issues.append(ValidationIssue("PROVENANCE", "Fact source hash does not match the filing.", fact.qname))
        if not fact.source.reviewer or not fact.source.reviewer.strip() or not fact.source.location:
            issues.append(ValidationIssue("PROVENANCE", "A reviewed source location is required.", fact.qname))
        prefix = fact.qname.split(":", 1)[0]
        if ":" not in fact.qname or prefix not in taxonomy.namespaces:
            issues.append(ValidationIssue("QNAME-001", "Fact QName has no registered namespace.", fact.qname))
    issues.extend(_check_entity_info(snapshot))                        # K
    issues.extend(_check_contexts(snapshot))                           # B, E
    issues.extend(_check_units(snapshot))                              # B, F
    issues.extend(_check_fact_structure(snapshot))                     # B, C
    issues.extend(_check_concept_validity(snapshot, taxonomy))         # D
    issues.extend(_check_period_type(snapshot, taxonomy))              # E
    issues.extend(_check_unit_type(snapshot, taxonomy))                # F
    issues.extend(_check_calculations(snapshot, taxonomy))             # G
    issues.extend(_check_mandatory_facts(snapshot, taxonomy))          # I, J
    issues.extend(_check_sbr_requirements(snapshot))                   # K
    return issues


def validate_xml(ixbrl_doc: str | bytes) -> list[ValidationIssue]:
    """Check A: XML well-formedness."""
    issues: list[ValidationIssue] = []
    try:
        root = ET.fromstring(ixbrl_doc.encode("utf-8") if isinstance(ixbrl_doc, str) else ixbrl_doc)
        ns = {"ix": "http://www.xbrl.org/2013/inlineXBRL", "link": "http://www.xbrl.org/2003/linkbase", "x": "http://www.xbrl.org/2003/instance"}
        reference = root.find(".//ix:references/link:schemaRef", ns)
        if reference is None or not reference.get("{http://www.w3.org/1999/xlink}href"):
            issues.append(ValidationIssue("IX-001", "A taxonomy schema reference is required."))
        if root.find(".//ix:resources/x:xbrl", ns) is not None:
            issues.append(ValidationIssue("IX-002", "Contexts and units must be direct resources children."))
    except ET.ParseError as exc:
        issues.append(ValidationIssue(
            code="XML-001",
            message=f"iXBRL document is not well-formed XML: {exc}",
            severity="error",
        ))
    return issues


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def _check_entity_info(snap: FilingSnapshot) -> list[ValidationIssue]:
    """K: KVK filing requirements — entity metadata completeness."""
    issues: list[ValidationIssue] = []
    if not snap.entity_name or not snap.entity_name.strip():
        issues.append(ValidationIssue(
            code="KVK-001",
            message="Entity name is required for KVK filing.",
            severity="error",
        ))
    if not snap.kvk_number or len(snap.kvk_number) != 8 or not snap.kvk_number.isdigit():
        issues.append(ValidationIssue(
            code="KVK-002",
            message="KVK number must be exactly 8 digits.",
            severity="error",
        ))
    if snap.period_start >= snap.period_end:
        issues.append(ValidationIssue(
            code="KVK-003",
            message="Reporting period start must precede end date.",
            severity="error",
        ))
    return issues


def _check_contexts(snap: FilingSnapshot) -> list[ValidationIssue]:
    """B/E: Context validity."""
    issues: list[ValidationIssue] = []
    ctx_ids = {c.id for c in snap.contexts}

    for fact in snap.facts:
        if fact.context_id not in ctx_ids:
            issues.append(ValidationIssue(
                code="CTX-001",
                message=f"Fact references unknown context '{fact.context_id}'.",
                concept=fact.qname,
                severity="error",
            ))

    if len(ctx_ids) != len(snap.contexts):
        issues.append(ValidationIssue("CTX-006", "Context IDs must be unique."))
    for ctx in snap.contexts:
        if ctx.entity_identifier != snap.kvk_number or ctx.entity_scheme != "http://www.kvk.nl/kvk-id":
            issues.append(ValidationIssue("CTX-005", "Context entity must match the filing and KVK scheme."))
        if ctx.instant is None and (ctx.start_date is None or ctx.end_date is None):
            issues.append(ValidationIssue(
                code="CTX-002",
                message=f"Context '{ctx.id}' has neither instant nor start/end dates.",
                severity="error",
            ))
        if ctx.start_date and ctx.end_date and ctx.start_date >= ctx.end_date:
            issues.append(ValidationIssue(
                code="CTX-003",
                message=f"Context '{ctx.id}' has start_date >= end_date.",
                severity="error",
            ))
        if not ctx.entity_identifier:
            issues.append(ValidationIssue(
                code="CTX-004",
                message=f"Context '{ctx.id}' missing entity identifier.",
                severity="error",
            ))
    return issues


def _check_units(snap: FilingSnapshot) -> list[ValidationIssue]:
    """B/F: Unit validity."""
    issues: list[ValidationIssue] = []
    unit_ids = {u.id for u in snap.units}

    for fact in snap.facts:
        if fact.kind == "numeric" and fact.unit_id:
            if fact.unit_id not in unit_ids:
                issues.append(ValidationIssue(
                    code="UNIT-001",
                    message=f"Fact references unknown unit '{fact.unit_id}'.",
                    concept=fact.qname,
                    severity="error",
                ))

    if len(unit_ids) != len(snap.units):
        issues.append(ValidationIssue("UNIT-007", "Unit IDs must be unique."))
    for unit in snap.units:
        if not (re.fullmatch(r"iso4217:[A-Z]{3}", unit.measure) or unit.measure in {"xbrli:pure", "xbrli:shares"}):
            issues.append(ValidationIssue("UNIT-008", "Unsupported unit measure; use a currency, pure or shares measure."))
        if not unit.measure:
            issues.append(ValidationIssue(
                code="UNIT-002",
                message=f"Unit '{unit.id}' has no measure.",
                severity="error",
            ))
        # ISO 4217 currency measures should use iso4217: prefix
        if unit.measure and not ":" in unit.measure and len(unit.measure) == 3:
            issues.append(ValidationIssue(
                code="UNIT-003",
                message=(
                    f"Unit '{unit.id}' measure '{unit.measure}' appears to be a currency "
                    "but is missing the 'iso4217:' prefix (e.g. iso4217:EUR)."
                ),
                severity="warning",
            ))
    return issues


def _check_fact_structure(snap: FilingSnapshot) -> list[ValidationIssue]:
    """B/C: Basic fact structural rules."""
    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()

    aspects = set()
    for fact in snap.facts:
        aspect = (fact.qname, fact.context_id, fact.unit_id)
        if aspect in aspects:
            issues.append(ValidationIssue("FACT-005", "Duplicate concept/context/unit fact.", fact.qname))
        aspects.add(aspect)
        if fact.id in seen_ids:
            issues.append(ValidationIssue(
                code="FACT-001",
                message=f"Duplicate fact id '{fact.id}'.",
                concept=fact.qname,
                severity="error",
            ))
        seen_ids.add(fact.id)

        if fact.kind == "numeric":
            if not fact.unit_id and not fact.nil:
                issues.append(ValidationIssue(
                    code="FACT-002",
                    message="Numeric fact is missing unit reference.",
                    concept=fact.qname,
                    severity="error",
                ))
            if fact.decimals is None and not fact.nil:
                issues.append(ValidationIssue(
                    code="FACT-003",
                    message="Numeric fact is missing decimals attribute.",
                    concept=fact.qname,
                    severity="error",
                ))
        if fact.nil and fact.value is not None:
            issues.append(ValidationIssue(
                code="FACT-004",
                message="Nil fact must not carry a value.",
                concept=fact.qname,
                severity="error",
            ))
    return issues


def _check_concept_validity(
    snap: FilingSnapshot,
    taxonomy: "TaxonomyRelease | EnrichedTaxonomyRelease",
) -> list[ValidationIssue]:
    """D: All fact qnames must be in the active entry point."""
    issues: list[ValidationIssue] = []
    from KVK_v2.registry import EnrichedTaxonomyRelease
    if not isinstance(taxonomy, EnrichedTaxonomyRelease):
        return issues  # Can't check without enriched taxonomy

    ep_concepts = {
        c.qname for c in taxonomy.get_concepts_for_ep(
            snap.entry_point_key, exclude_abstract=False
        )
    }
    for fact in snap.facts:
        concept = taxonomy.get_concept(fact.qname)
        if concept:
            if concept.abstract or (fact.nil and not concept.nillable):
                issues.append(ValidationIssue("CONCEPT-002", "Abstract or non-nillable concept used incorrectly.", fact.qname))
            if concept.is_numeric() and fact.kind != "numeric":
                issues.append(ValidationIssue("TYPE-001", "Numeric concept requires a numeric fact.", fact.qname))
            if "booleanItemType" in concept.data_type and fact.kind != "boolean":
                issues.append(ValidationIssue("TYPE-001", "Boolean concept requires a boolean fact.", fact.qname))
            if "dateItemType" in concept.data_type and fact.kind != "date":
                issues.append(ValidationIssue("TYPE-001", "Date concept requires a date fact.", fact.qname))
        if fact.qname not in ep_concepts:
            issues.append(ValidationIssue(
                code="CONCEPT-001",
                message=(
                    f"Concept '{fact.qname}' is not defined in entry point "
                    f"'{snap.entry_point_key}' of taxonomy '{snap.taxonomy_id}'."
                ),
                concept=fact.qname,
                severity="error",
            ))
    return issues


def _check_period_type(
    snap: FilingSnapshot,
    taxonomy: "TaxonomyRelease | EnrichedTaxonomyRelease",
) -> list[ValidationIssue]:
    """E: Period type of context must match concept's periodType."""
    issues: list[ValidationIssue] = []
    from KVK_v2.registry import EnrichedTaxonomyRelease
    if not isinstance(taxonomy, EnrichedTaxonomyRelease):
        return issues

    ctx_map = {c.id: c for c in snap.contexts}
    for fact in snap.facts:
        concept = taxonomy.get_concept(fact.qname)
        if not concept or not concept.period_type:
            continue
        ctx = ctx_map.get(fact.context_id)
        if not ctx:
            continue
        is_instant_ctx = ctx.instant is not None
        is_instant_concept = concept.period_type == "instant"
        if is_instant_ctx != is_instant_concept:
            issues.append(ValidationIssue(
                code="PERIOD-001",
                message=(
                    f"Concept '{fact.qname}' has periodType='{concept.period_type}' "
                    f"but context '{fact.context_id}' is a "
                    f"{'instant' if is_instant_ctx else 'duration'} context."
                ),
                concept=fact.qname,
                severity="error",
            ))
    return issues


def _check_unit_type(
    snap: FilingSnapshot,
    taxonomy: "TaxonomyRelease | EnrichedTaxonomyRelease",
) -> list[ValidationIssue]:
    """F: Monetary concepts must have a currency unit; pure concepts no unit."""
    issues: list[ValidationIssue] = []
    from KVK_v2.registry import EnrichedTaxonomyRelease
    if not isinstance(taxonomy, EnrichedTaxonomyRelease):
        return issues

    unit_map = {u.id: u for u in snap.units}
    for fact in snap.facts:
        if fact.kind != "numeric" or fact.nil:
            continue
        concept = taxonomy.get_concept(fact.qname)
        if not concept:
            continue
        unit = unit_map.get(fact.unit_id or "")
        if "monetaryItemType" in concept.data_type:
            if not unit:
                issues.append(ValidationIssue(
                    code="UNIT-004",
                    message=f"Monetary concept '{fact.qname}' has no unit.",
                    concept=fact.qname,
                    severity="error",
                ))
            elif "iso4217" not in (unit.measure or "") and len(unit.measure or "") != 3:
                issues.append(ValidationIssue(
                    code="UNIT-005",
                    message=(
                        f"Monetary concept '{fact.qname}' unit '{unit.measure}' "
                        "does not appear to be an ISO 4217 currency."
                    ),
                    concept=fact.qname,
                    severity="warning",
                ))
        elif "pureItemType" in concept.data_type:
            if unit and unit.measure and "pure" not in unit.measure.lower():
                issues.append(ValidationIssue(
                    code="UNIT-006",
                    message=f"Pure concept '{fact.qname}' should not have a currency unit.",
                    concept=fact.qname,
                    severity="warning",
                ))
    return issues


def _check_calculations(
    snap: FilingSnapshot,
    taxonomy: "TaxonomyRelease | EnrichedTaxonomyRelease",
) -> list[ValidationIssue]:
    """G: Calculation linkbase — parent should equal weighted sum of children."""
    issues: list[ValidationIssue] = []
    from KVK_v2.registry import EnrichedTaxonomyRelease
    if not isinstance(taxonomy, EnrichedTaxonomyRelease):
        return issues

    facts = {(f.qname, f.context_id, f.unit_id): f for f in snap.facts
             if f.kind == "numeric" and not f.nil and isinstance(f.value, Decimal) and f.value.is_finite()}
    networks = {}
    for concept in taxonomy.get_concepts_for_ep(snap.entry_point_key):
        for arc in concept.calc_relationships:
            networks.setdefault((arc.link_role, arc.parent_qname), {})[arc.child_qname] = Decimal(str(arc.weight))
    for (role, parent), children in networks.items():
        for (qname, context, unit), parent_fact in facts.items():
            if qname != parent:
                continue
            child_facts = [(facts.get((child, context, unit)), weight) for child, weight in children.items()]
            if not child_facts or any(f is None for f, _ in child_facts):
                continue
            total = sum((f.value * weight for f, weight in child_facts), Decimal(0))
            tolerance = Decimal(5).scaleb(-(parent_fact.decimals or 0) - 1)
            tolerance += sum((abs(weight) * Decimal(5).scaleb(-(f.decimals or 0) - 1) for f, weight in child_facts), Decimal(0))
            if abs(parent_fact.value - total) > tolerance:
                issues.append(ValidationIssue("CALC-001", f"Parent {parent_fact.value} differs from weighted sum {total}.", parent, rule_ref=role))
    return issues


def _check_mandatory_facts(
    snap: FilingSnapshot,
    taxonomy: "TaxonomyRelease | EnrichedTaxonomyRelease",
) -> list[ValidationIssue]:
    """I/J: Check mandatory and conditional facts from the rules engine."""
    issues: list[ValidationIssue] = []
    from KVK_v2.registry import EnrichedTaxonomyRelease
    from KVK_v2.taxonomy.rules import MandatoryStatus

    if not isinstance(taxonomy, EnrichedTaxonomyRelease) or taxonomy.rules_engine is None:
        # Fall back to legacy requirements check
        return _check_legacy_requirements(snap, taxonomy)

    mapped_qnames = {fact.qname for fact in snap.facts if not fact.nil}
    ep_key = snap.entry_point_key
    rules = taxonomy.rules_engine.get_rules_for_entry_point(ep_key)

    for rule in rules:
        from KVK_v2.taxonomy.rules import RuleType
        if rule.rule_type != RuleType.EXISTENCE:
            continue
        if not rule.concept_qname:
            continue
        is_present = rule.concept_qname in mapped_qnames
        is_reviewed = rule.rule_id in snap.reviewed_requirement_ids

        if rule.status == MandatoryStatus.MANDATORY and not is_present:
            issues.append(ValidationIssue(
                code="REQ-001",
                message=(
                    f"Required fact is missing: '{rule.concept_qname}'. "
                    f"{rule.error_message_nl or ''}"
                ).strip(),
                concept=rule.concept_qname,
                severity="error",
                rule_ref=rule.rule_id,
            ))
        elif rule.status == MandatoryStatus.CONDITIONAL and not is_present and not is_reviewed:
            issues.append(ValidationIssue(
                code="REQ-002",
                message=(
                    f"Conditional fact may be required: '{rule.concept_qname}'. "
                    f"{rule.condition_nl or 'Verplicht wanneer van toepassing.'} "
                    "Mark as reviewed if not applicable."
                ).strip(),
                concept=rule.concept_qname,
                severity="error",
                rule_ref=rule.rule_id,
            ))
    return issues


def _check_legacy_requirements(
    snap: FilingSnapshot,
    taxonomy: "TaxonomyRelease | EnrichedTaxonomyRelease",
) -> list[ValidationIssue]:
    """Fallback mandatory check using legacy TaggingRequirement list."""
    issues: list[ValidationIssue] = []
    reqs = taxonomy.requirements.get(snap.entry_point_key, ())
    mapped_qnames = {fact.qname for fact in snap.facts if not fact.nil}
    for req in reqs:
        present = (not req.qname or req.qname in mapped_qnames) and (not req.section or req.section in snap.report_sections)
        if req.conditional:
            if req.id not in snap.reviewed_requirement_ids:
                issues.append(ValidationIssue("CONDITIONAL_REVIEW", f"Conditional requirement needs review: {req.id}."))
        elif not present:
            issues.append(ValidationIssue("MANDATORY_TAG", f"Required fact or section missing: {req.id}.", req.qname))

    return issues


def _check_sbr_requirements(snap: FilingSnapshot) -> list[ValidationIssue]:
    """K: KVK/SBR-specific filing requirements."""
    issues: list[ValidationIssue] = []
    if not snap.is_final:
        issues.append(ValidationIssue(
            code="SBR-001",
            message="Filing is not marked as final. Set is_final=True before submission.",
            severity="warning",
        ))
    if not snap.signatory_name:
        issues.append(ValidationIssue(
            code="SBR-002",
            message="Signatory name is required for KVK SBR filing.",
            severity="warning",
        ))
    if not snap.approval_date:
        issues.append(ValidationIssue(
            code="SBR-003",
            message="Approval date is required for KVK SBR filing.",
            severity="warning",
        ))
    if len(snap.facts) == 0:
        issues.append(ValidationIssue(
            code="SBR-004",
            message="Filing contains no XBRL facts.",
            severity="error",
        ))
    if len(snap.contexts) == 0:
        issues.append(ValidationIssue(
            code="SBR-005",
            message="Filing contains no XBRL contexts.",
            severity="error",
        ))
    return issues
