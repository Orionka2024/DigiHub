"""Rules engine: determines mandatory/conditional/optional status of XBRL concepts.

The mandatory status of a concept is derived from XBRL formula linkbases
(ea:existenceAssertion elements in *-for.xml files), NOT from the mere presence
of a concept in an XSD schema.

Architecture:
  ValidationRule  →  parsed from formula linkbases
  RulesEngine     →  indexes rules by concept + entry point, answers queries
  ChecklistItem   →  UI-ready representation of one concept in the checklist
  ChecklistSection →  grouped checklist items
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from taxonomy.concept import ConceptMetadata
    from models import FilingSnapshot


class MandatoryStatus(str, Enum):
    MANDATORY = "mandatory"
    CONDITIONAL = "conditional"
    OPTIONAL = "optional"
    NOT_APPLICABLE = "not_applicable"


class RuleType(str, Enum):
    EXISTENCE = "existence"       # ea:existenceAssertion
    VALUE = "value"               # va:valueAssertion (calculation)
    CALCULATION = "calculation"   # xbrl:calculationArc


@dataclass(frozen=True)
class ValidationRule:
    """One rule extracted from the official taxonomy formula/validation linkbases.

    For existence assertions the rule expresses: 'concept X must exist in the
    instance document (possibly subject to a condition)'.
    For value assertions the rule expresses a mathematical relationship between
    concepts.

    The mandatory_status is determined as follows:
    - MANDATORY   : existenceAssertion with no boolean-filter condition
    - CONDITIONAL : existenceAssertion wrapped in a boolean-filter that depends
                    on other facts being present or having specific values
    - OPTIONAL    : concept not covered by any existenceAssertion
    """
    rule_id: str              # assertion/@id from taxonomy
    rule_type: RuleType
    status: MandatoryStatus

    # The concept this rule targets (None for multi-concept value assertions)
    concept_qname: str | None

    # Human-readable condition (empty = unconditionally applies)
    condition_nl: str = ""
    condition_en: str = ""
    # Raw XPath/formula test expression for reference
    test_expression: str = ""

    # Dutch error message from *-for-generic-msg-unsatisfied-nl.xml
    error_message_nl: str = ""
    error_message_en: str = ""

    # Which entry points declare this rule
    entry_points: tuple[str, ...] = ()

    # Source file for auditability
    source_file: str = ""
    taxonomy_version: str = ""


@dataclass
class ChecklistItem:
    """One line in the mandatory checklist UI."""
    concept_qname: str
    label_nl: str
    label_en: str
    data_type: str
    period_type: str
    balance: str | None
    status: MandatoryStatus
    condition_nl: str
    rule_ids: list[str]
    # True if the concept already has a mapped fact in the current snapshot
    is_satisfied: bool = False
    # Derived from snapshot: fact value if satisfied
    fact_value: str | None = None


@dataclass
class ChecklistSection:
    """A labelled group of checklist items (e.g. 'Balance Sheet — Banks')."""
    section_id: str
    title_nl: str
    title_en: str
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def satisfied(self) -> int:
        return sum(1 for i in self.items if i.is_satisfied)

    @property
    def mandatory_count(self) -> int:
        return sum(1 for i in self.items if i.status == MandatoryStatus.MANDATORY)

    @property
    def conditional_count(self) -> int:
        return sum(1 for i in self.items if i.status == MandatoryStatus.CONDITIONAL)


class RulesEngine:
    """Answers taxonomy-driven mandatory/conditional/optional queries.

    Populated by TaxonomyImporter during package loading.
    """

    def __init__(self) -> None:
        # rule_id → ValidationRule
        self._rules: dict[str, ValidationRule] = {}
        # entry_point_key → list[rule_id]
        self._rules_by_ep: dict[str, list[str]] = {}
        # (concept_qname, entry_point_key) → list[rule_id]
        self._rules_by_concept_ep: dict[tuple[str, str], list[str]] = {}

    def add_rule(self, rule: ValidationRule) -> None:
        existing = self._rules.get(rule.rule_id)
        if existing:
            rule = replace(rule, entry_points=tuple(sorted(set(existing.entry_points) | set(rule.entry_points))))
        self._rules[rule.rule_id] = rule
        for ep in rule.entry_points:
            ids = self._rules_by_ep.setdefault(ep, [])
            if rule.rule_id not in ids:
                ids.append(rule.rule_id)
            if rule.concept_qname:
                key = (rule.concept_qname, ep)
                ids = self._rules_by_concept_ep.setdefault(key, [])
                if rule.rule_id not in ids:
                    ids.append(rule.rule_id)

    def get_concept_status(
        self, qname: str, entry_point_key: str
    ) -> MandatoryStatus:
        """Return the mandatory status of a concept for a given entry point."""
        key = (qname, entry_point_key)
        rule_ids = self._rules_by_concept_ep.get(key, [])
        if not rule_ids:
            return MandatoryStatus.OPTIONAL
        statuses = {self._rules[rid].status for rid in rule_ids}
        # Most restrictive status wins
        if MandatoryStatus.MANDATORY in statuses:
            return MandatoryStatus.MANDATORY
        if MandatoryStatus.CONDITIONAL in statuses:
            return MandatoryStatus.CONDITIONAL
        return MandatoryStatus.OPTIONAL

    def get_rules_for_concept(
        self, qname: str, entry_point_key: str
    ) -> list[ValidationRule]:
        """Return all rules that reference this concept for this entry point."""
        key = (qname, entry_point_key)
        return [self._rules[rid] for rid in self._rules_by_concept_ep.get(key, [])]

    def get_rules_for_entry_point(self, entry_point_key: str) -> list[ValidationRule]:
        """Return all rules for an entry point."""
        return [self._rules[rid] for rid in self._rules_by_ep.get(entry_point_key, [])]

    def get_all_rules(self) -> list[ValidationRule]:
        return list(self._rules.values())

    def build_checklist(
        self,
        concepts: list["ConceptMetadata"],
        entry_point_key: str,
        snapshot: "FilingSnapshot | None" = None,
    ) -> list[ChecklistSection]:
        """Build a dynamic checklist from taxonomy concepts + rules.

        Groups concepts by their presentation link role to create sections.
        Only non-abstract concepts are listed.
        """
        # Collect mapped qnames for satisfaction check
        mapped_qnames: set[str] = set()
        fact_values: dict[str, str] = {}
        if snapshot:
            for fact in snapshot.facts:
                mapped_qnames.add(fact.qname)
                fact_values[fact.qname] = str(fact.value) if fact.value is not None else ""

        # Group by link role (section)
        sections_map: dict[str, ChecklistSection] = {}
        section_order: list[str] = []

        for concept in concepts:
            if concept.abstract:
                continue
            if entry_point_key not in concept.entry_points:
                continue

            status = self.get_concept_status(concept.qname, entry_point_key)
            if status == MandatoryStatus.NOT_APPLICABLE:
                continue

            rules = self.get_rules_for_concept(concept.qname, entry_point_key)
            condition_nl = ""
            if rules:
                conditions = [r.condition_nl for r in rules if r.condition_nl]
                condition_nl = conditions[0] if conditions else ""

            item = ChecklistItem(
                concept_qname=concept.qname,
                label_nl=concept.label_nl or concept.local_name,
                label_en=concept.label_en,
                data_type=concept.data_type,
                period_type=concept.period_type,
                balance=concept.balance,
                status=status,
                condition_nl=condition_nl,
                rule_ids=[r.rule_id for r in rules],
                is_satisfied=(concept.qname in mapped_qnames or (status == MandatoryStatus.CONDITIONAL
                              and snapshot is not None and bool(rules)
                              and all(r.rule_id in snapshot.reviewed_requirement_ids for r in rules))),
                fact_value=fact_values.get(concept.qname),
            )

            section_key = concept.pres_link_role or "general"
            if section_key not in sections_map:
                title = _linkrole_to_title(section_key)
                sections_map[section_key] = ChecklistSection(
                    section_id=section_key,
                    title_nl=title,
                    title_en=title,
                )
                section_order.append(section_key)
            sections_map[section_key].items.append(item)

        return [sections_map[k] for k in section_order]


def _linkrole_to_title(link_role: str) -> str:
    """Convert a taxonomy link role URI to a human-readable section title."""
    if not link_role or link_role == "general":
        return "Algemeen / General"
    # Extract the last segment: urn:kvk:linkrole:balance-sheet-banks
    part = link_role.rsplit(":", 1)[-1] if ":" in link_role else link_role
    return part.replace("-", " ").replace("_", " ").title()
