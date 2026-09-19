"""AssertionRule – parsed XBRL Formula linkbase assertion.

The Nederlandse Taxonomie encodes mandatory / conditional concept requirements
using XBRL Formula linkbases (*-for.xml).  This module models the parsed rules.

Key NT21 patterns:
  - ea:existenceAssertion test=".eq 1" severity=ERROR  → concept is MANDATORY
  - ea:existenceAssertion with variable-set-precondition → CONDITIONAL
  - va:valueAssertion (e.g. Assets = EquityAndLiabilities) → CONDITIONAL (calc)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AssertionRule:
    """One parsed assertion from an XBRL Formula linkbase."""

    # ── Identity ───────────────────────────────────────────────────────────────
    id: str                     # assertion XML id attribute
    assertion_type: str         # "existence" | "value"
    severity: str               # "ERROR" | "WARNING" | "OK"

    # ── Concept being asserted ─────────────────────────────────────────────────
    concept_qname: str          # e.g. "jenv-bw2-i:Assets"

    # ── Condition ──────────────────────────────────────────────────────────────
    precondition_qnames: list[str] = field(default_factory=list)
    # If non-empty → this assertion only fires when ALL precondition facts exist.
    # This makes the asserted concept CONDITIONAL rather than MANDATORY.

    # ── For value assertions ────────────────────────────────────────────────────
    test_expression: str | None = None   # XPath test expression

    # ── Taxonomy provenance ─────────────────────────────────────────────────────
    link_role: str = ""          # urn:kvk:linkrole:balance-sheet etc.
    source_file: str = ""        # basename of the formula linkbase file

    # ── Derived status ──────────────────────────────────────────────────────────
    @property
    def derived_status(self) -> str:
        """Return 'mandatory', 'conditional', or 'optional'."""
        if self.assertion_type == "existence":
            if self.severity == "ERROR" and not self.precondition_qnames:
                return "mandatory"
            return "conditional"
        # value assertions and warnings are always conditional
        return "conditional"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "assertion_type": self.assertion_type,
            "severity": self.severity,
            "concept_qname": self.concept_qname,
            "precondition_qnames": self.precondition_qnames,
            "test_expression": self.test_expression,
            "link_role": self.link_role,
            "source_file": self.source_file,
            "derived_status": self.derived_status,
        }
