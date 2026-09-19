"""Review-gated mapping ledger for Word source locations to taxonomy facts."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from datetime import date
from decimal import Decimal

from .docx_extract import ExtractedDocument
from .models import Fact, SourceRef


@dataclass(frozen=True)
class MappingDecision:
    source_node_id: str
    source_location: str
    qname: str
    context_id: str
    kind: str
    value: Decimal | str | bool | None
    unit_id: str | None = None
    decimals: int | None = None
    reviewer: str | None = None


def fact_from_decision(document: ExtractedDocument, decision: MappingDecision) -> Fact:
    if not decision.reviewer or not decision.reviewer.strip():
        raise ValueError("A reviewer must approve every mapping decision.")
    if decision.source_node_id not in {node.id for node in document.nodes}:
        raise ValueError("Mapping refers to a source node outside this document.")
    node = next(n for n in document.nodes if n.id == decision.source_node_id)
    extracted = source_value(node, decision.source_location)
    identity = json.dumps([document.sha256, node.id, decision.source_location,
                           decision.qname, decision.context_id, decision.unit_id])
    value = decision.value
    if decision.kind == "date" and isinstance(value, str):
        value = date.fromisoformat(value)
    return Fact(
        id="fact-" + sha256(identity.encode()).hexdigest()[:32], qname=decision.qname,
        context_id=decision.context_id, value=value, kind=decision.kind,  # type: ignore[arg-type]
        source=SourceRef(document.sha256, decision.source_location, extracted, decision.reviewer.strip()),
        unit_id=decision.unit_id, decimals=decision.decimals,
    )


def source_value(node, location: str) -> str:
    if node.kind == "paragraph" and location == node.location:
        return node.text
    match = re.fullmatch(re.escape(node.location) + r", Row (\d+), Col (\d+)", location)
    if node.kind == "table" and match:
        row, col = (int(v) - 1 for v in match.groups())
        if row >= 0 and col >= 0 and row < len(node.rows) and col < len(node.rows[row]):
            return node.rows[row][col]
    raise ValueError("Source location must identify an existing paragraph or table cell.")
