from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from docx_extract import SourceNode
from registry import TaggingRequirement


def _camel_to_words(text: str) -> set[str]:
    """Splits CamelCase into lowercase words."""
    words = re.sub("([a-z])([A-Z])", r"\g<1> \g<2>", text).split()
    return {w.lower() for w in words}

def _clean_text(text: str) -> set[str]:
    """Cleans punctuation and returns lowercase words."""
    text = re.sub(r"[^\w\s]", "", text)
    return {w.lower() for w in text.split() if w.strip()}

def recommend_tags(
    table_node: SourceNode,
    requirements: list[Any]
) -> list[dict[str, Any]]:
    """Heuristically matches table rows to taxonomy requirements."""
    recommendations = []
    targets = []
    for concept in requirements:
        qname = getattr(concept, "qname", None)
        if not qname:
            continue
        labels = [getattr(concept, "label_nl", ""), getattr(concept, "label_en", "")]
        variants = [_clean_text(label) for label in labels if label]
        variants.append(_camel_to_words(qname.split(":")[-1]))
        targets.append((concept, variants))

    for r_idx, row in enumerate(table_node.rows):
        if not row or not row[0].strip():
            continue
        words = _clean_text(row[0])
        ranked = []
        for concept, variants in targets:
            # Jaccard overlap avoids treating 'Assets' and 'Current Assets' as
            # identical. Scores describe label similarity, not accounting certainty.
            score = max((len(words & target) / len(words | target)
                         for target in variants if words | target), default=0)
            if score >= 0.5:
                ranked.append((score, concept))
        ranked.sort(key=lambda item: (-item[0], item[1].qname))
        if not ranked:
            continue
        score, concept = ranked[0]
        for col_idx, cell in enumerate(row[1:], start=1):
            try:
                value = str(parse_number(cell))
            except ValueError:
                continue
            # Only explicit column year headers provide a period hint.
            year = None
            for header in reversed(table_node.rows[:r_idx]):
                if col_idx < len(header) and re.fullmatch(r"20\d{2}", header[col_idx].strip()):
                    year = int(header[col_idx].strip())
                    break
            recommendations.append({
                "source_node_id": table_node.id,
                "source_location": f"{table_node.location}, Row {r_idx + 1}, Col {col_idx + 1}",
                "row_index": r_idx, "col_index": col_idx,
                "qname": concept.qname, "value": value, "kind": "numeric",
                "label": getattr(concept, "label_en", "") or getattr(concept, "label_nl", "") or concept.qname,
                "source_label": row[0], "source_text": cell,
                "period_type": getattr(concept, "period_type", ""), "year_hint": year,
                "match_score": round(score, 3),
                "alternatives": [c.qname for _, c in ranked[1:4]],
            })
    return recommendations


def parse_number(text: str, locale: str = "nl") -> Decimal:
    """Parse reviewed Dutch or English amounts; never guess separator locale."""
    value = text.strip().replace("\u00a0", " ")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    decimal_sep, grouping = (",", ".") if locale == "nl" else (".", ",")
    pattern = rf"[+-]?(?:\d+|\d{{1,3}}(?:{re.escape(grouping)}\d{{3}})+)(?:{re.escape(decimal_sep)}\d+)?"
    if not re.fullmatch(pattern, value):
        raise ValueError("Amount does not match the selected numeric locale.")
    result = Decimal(value.replace(grouping, "").replace(decimal_sep, "."))
    return -result if negative else result
