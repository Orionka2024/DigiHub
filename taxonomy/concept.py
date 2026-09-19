"""Concept metadata model for taxonomy-driven XBRL reporting.

Every concept that appears in the application is backed by a ConceptMetadata
instance derived from the official Nederlandse Taxonomie package.  Nothing is
hard-coded; all metadata originates from the taxonomy files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class CalcRelationship:
    """A calculation-linkbase arc: parent sums weighted children."""
    parent_qname: str
    child_qname: str
    weight: float          # typically +1 or -1
    order: float
    link_role: str


@dataclass(frozen=True)
class PresentationRelationship:
    """A presentation-linkbase arc: parent → child display order."""
    parent_qname: str
    child_qname: str
    order: float
    link_role: str
    preferred_label: str | None = None


@dataclass(frozen=True)
class DimensionRelationship:
    """A definition-linkbase hypercube membership."""
    hypercube_qname: str
    dimension_qname: str
    domain_qname: str | None
    members: tuple[str, ...] = ()    # explicit member qnames
    closed: bool = False
    context_element: str = "segment"  # or "scenario"


@dataclass(frozen=True)
class Reference:
    """A reference-linkbase entry pointing to a legal/regulatory source."""
    role: str
    parts: dict[str, str] = field(default_factory=dict)   # part name → value


MandatoryStatusLiteral = Literal["mandatory", "conditional", "optional", "not_applicable"]


@dataclass
class ConceptMetadata:
    """Full metadata for a single XBRL concept from the official taxonomy.

    All fields are sourced from the taxonomy package files:
    - XSD element attributes → qname, namespace, local_name, data_type,
      period_type, balance, abstract, nillable
    - Label linkbases → label_nl, label_en, documentation
    - Presentation linkbases → parent_qname, pres_children
    - Calculation linkbases → calc_relationships
    - Definition linkbases → dimension_relationships
    - Reference linkbases → references
    - Formula linkbases → mandatory_status, validation_rules

    The mandatory_status is determined exclusively by ea:existenceAssertion
    elements in the formula linkbase files (*-for.xml).  It is NEVER derived
    from a concept's mere presence in an XSD.
    """
    # Core identity
    qname: str                    # e.g. "kvk-i:Assets" (prefix:localName)
    namespace: str                # full NS URI
    local_name: str               # "Assets"
    taxonomy_version: str         # e.g. "NT21_KVK_20261209_b"

    # Labels (from label linkbases)
    label_nl: str = ""            # Dutch label (verboseLabel preferred)
    label_en: str = ""            # English label if available
    documentation: str = ""       # definition/documentation label

    # XSD attributes
    data_type: str = ""           # e.g. "xbrli:monetaryItemType"
    period_type: str = ""         # "instant" | "duration"
    balance: str | None = None    # "debit" | "credit" | None
    abstract: bool = False
    nillable: bool = True
    substitution_group: str = ""  # e.g. "xbrli:item"

    # Entry points that include this concept
    entry_points: list[str] = field(default_factory=list)

    # Structural relationships
    parent_qname: str | None = None
    pres_children: list[str] = field(default_factory=list)
    pres_order: float = 0.0
    pres_link_role: str = ""
    calc_relationships: list[CalcRelationship] = field(default_factory=list)
    dimension_relationships: list[DimensionRelationship] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)

    # Mandatory/conditional status (derived from formula linkbases)
    mandatory_status: MandatoryStatusLiteral = "optional"
    # Which rule(s) drive the mandatory status
    rule_ids: list[str] = field(default_factory=list)
    # Human-readable condition (empty if unconditionally mandatory)
    condition_nl: str = ""
    condition_en: str = ""

    def is_monetary(self) -> bool:
        return "monetaryItemType" in self.data_type

    def is_text(self) -> bool:
        return "stringItemType" in self.data_type or "normalizedStringItemType" in self.data_type

    def is_numeric(self) -> bool:
        numeric_types = (
            "monetaryItemType", "decimalItemType", "integerItemType",
            "sharesItemType", "pureItemType", "percentItemType",
        )
        return any(t in self.data_type for t in numeric_types)

    def __repr__(self) -> str:
        return f"ConceptMetadata({self.qname!r}, status={self.mandatory_status!r})"
