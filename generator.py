"""iXBRL (Inline XBRL 1.1) generator for Dutch KVK annual accounts.

Constructs XHTML embedding XBRL facts using the
Inline XBRL specification (IX 1.1, http://www.xbrl.org/2013/inlineXBRL).

Key design principles:
  * Every generated fact references a concept from the installed official
    taxonomy.  No concepts are invented.
  * Contexts, units and entity identifiers follow the SBR/KVK requirements:
      - Entity scheme: http://www.kvk.nl/kvk-id
      - Currency unit: ISO 4217 (EUR)
  * Numeric facts use ix:nonFraction with decimals and optional scale/sign.
  * Text facts use ix:nonNumeric.
  * Dimensional contexts use xbrldi:explicitMember inside xbrli:segment.
  * The ix:header block contains all contexts and units; facts appear inline
    in the document body.
  * Hidden facts (those not tied to visible document text) go in ix:hidden.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Sequence

from models import Context, Fact, FilingSnapshot, Unit


# ---------------------------------------------------------------------------
# Namespace declarations for the XHTML/iXBRL envelope
# ---------------------------------------------------------------------------

_XHTML_NS = "http://www.w3.org/1999/xhtml"
_IX_NS = "http://www.xbrl.org/2013/inlineXBRL"
_XBRLI_NS = "http://www.xbrl.org/2003/instance"
_XBRLDI_NS = "http://xbrl.org/2006/xbrldi"
_LINK_NS = "http://www.xbrl.org/2003/linkbase"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_ISO4217_NS = "http://www.xbrl.org/2003/iso4217"
_NUM_NS = "http://www.xbrl.org/dtr/type/numeric"

# Default taxonomy namespaces (merged with release-specific namespaces at render time)
_DEFAULT_NS: dict[str, str] = {
    "ix":     _IX_NS,
    "xbrli":  _XBRLI_NS,
    "xbrldi": _XBRLDI_NS,
    "link":   _LINK_NS,
    "xlink":  _XLINK_NS,
    "iso4217": _ISO4217_NS,
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def generate_ixbrl(
    snapshot: FilingSnapshot,
    taxonomy_namespaces: dict[str, str] | None = None,
    entity_scheme: str = "http://www.kvk.nl/kvk-id",
    report_title: str = "Jaarrekening",
    *, entry_point: str | None = None, document=None,
) -> str:
    """Generate a complete iXBRL 1.1 document for the given snapshot.

    Parameters
    ----------
    snapshot:
        The frozen FilingSnapshot containing facts, contexts and units.
    taxonomy_namespaces:
        Additional namespace prefix → URI mappings from the taxonomy release.
    entity_scheme:
        The entity identifier scheme URI (default: KVK).
    report_title:
        Human-readable report title embedded in the XHTML <title> element.

    Returns
    -------
    str
        A UTF-8 string containing the complete XHTML/iXBRL document.
    """
    ns = dict(_DEFAULT_NS)
    if taxonomy_namespaces:
        ns.update(taxonomy_namespaces)

    builder = _IXBRLBuilder(
        snapshot=snapshot,
        namespaces=ns,
        entity_scheme=entity_scheme,
        report_title=report_title,
        entry_point=entry_point, document=document,
    )
    return builder.build()


# ---------------------------------------------------------------------------
# Internal builder
# ---------------------------------------------------------------------------

class _IXBRLBuilder:
    def __init__(
        self,
        snapshot: FilingSnapshot,
        namespaces: dict[str, str],
        entity_scheme: str,
        report_title: str,
        entry_point: str | None = None, document=None,
    ) -> None:
        self.snap = snapshot
        self.ns = namespaces
        self.entity_scheme = entity_scheme
        self.report_title = report_title
        self.entry_point = entry_point
        self.document = document
        # Facts split into visible (body) and hidden
        self._visible_facts: list[Fact] = []
        self._hidden_facts: list[Fact] = []
        self._classify_facts()

    def _classify_facts(self) -> None:
        """Split facts into visible (document-body) and hidden.

        Source-backed exports render a visible reviewed-facts table alongside
        the extracted source. Standalone generation without source uses hidden facts.
        """
        # Source rendering is required by the export service.
        self._hidden_facts = [] if self.document else list(self.snap.facts)
        self._visible_facts = list(self.snap.facts) if self.document else []

    # ----------------------------------------------------------------
    # Top-level builder
    # ----------------------------------------------------------------

    def build(self) -> str:
        ns_attrs = " ".join(
            f'xmlns:{prefix}="{_xml_escape(uri)}"' for prefix, uri in self.ns.items()
        )
        # Also declare taxonomy concept namespaces extracted from facts
        extra_ns = self._collect_fact_namespaces()
        extra_ns_attrs = " ".join(
            f'xmlns:{prefix}="{_xml_escape(uri)}"'
            for prefix, uri in extra_ns.items()
            if prefix not in self.ns
        )
        all_ns = f"{ns_attrs} {extra_ns_attrs}".strip()

        body = self._build_body()
        header = self._build_ix_header()

        doc = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="{_XHTML_NS}"
      {all_ns}
      xml:lang="nl">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/>
  <title>{_xml_escape(self.report_title)}</title>
  <style type="text/css">
    body {{ font-family: Arial, sans-serif; font-size: 10pt; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ccc; padding: 4px 8px; }}
    .xbrl-fact {{ background-color: #fffde7; }}
  </style>
</head>
<body>
{header}
{body}
</body>
</html>"""
        return doc

    def _collect_fact_namespaces(self) -> dict[str, str]:
        """Collect namespace prefixes referenced in fact qnames."""
        result: dict[str, str] = {}
        for fact in self.snap.facts:
            if ":" in fact.qname:
                prefix = fact.qname.split(":", 1)[0]
                if prefix not in self.ns and prefix not in result:
                    # We don't know the URI here; just note the prefix
                    # The URI should come from taxonomy_namespaces
                    pass
        # Also scan contexts for dimension member namespaces
        return result

    # ----------------------------------------------------------------
    # ix:header
    # ----------------------------------------------------------------

    def _build_ix_header(self) -> str:
        contexts_xml = "\n".join(
            self._render_context(ctx) for ctx in self.snap.contexts
        )
        units_xml = "\n".join(
            self._render_unit(u) for u in self.snap.units
        )
        hidden_xml = self._render_hidden_facts()

        return f"""  <div style="display:none"><ix:header>
    <ix:hidden>
{hidden_xml}
    </ix:hidden>
    <ix:references><link:schemaRef xlink:type="simple" xlink:href="{_xml_escape(self.entry_point or '')}"/></ix:references>
    <ix:resources>
{contexts_xml}
{units_xml}
    </ix:resources>
  </ix:header></div>"""

    def _render_context(self, ctx: Context) -> str:
        # Entity
        entity = f"""        <xbrli:entity>
          <xbrli:identifier scheme="{_xml_escape(ctx.entity_scheme)}">{
          _xml_escape(ctx.entity_identifier)}</xbrli:identifier>{
          self._render_segment(ctx)}
        </xbrli:entity>"""

        # Period
        if ctx.instant is not None:
            period = f"""        <xbrli:period>
          <xbrli:instant>{ctx.instant.isoformat()}</xbrli:instant>
        </xbrli:period>"""
        else:
            period = f"""        <xbrli:period>
          <xbrli:startDate>{ctx.start_date.isoformat()}</xbrli:startDate>  
          <xbrli:endDate>{ctx.end_date.isoformat()}</xbrli:endDate>
        </xbrli:period>"""

        return f"""      <xbrli:context id="{_xml_escape(ctx.id)}">
{entity}
{period}
      </xbrli:context>"""

    def _render_segment(self, ctx: Context) -> str:
        if not ctx.dimensions:
            return ""
        dims = "\n".join(
            f'            <xbrldi:explicitMember dimension="{_xml_escape(d.axis)}">'
            f'{_xml_escape(d.member)}</xbrldi:explicitMember>'
            for d in ctx.dimensions
        )
        return f"""
          <xbrli:segment>
{dims}
          </xbrli:segment>"""

    def _render_unit(self, unit: Unit) -> str:
        if ":" in unit.measure:
            # e.g. iso4217:EUR
            measure_text = unit.measure
        else:
            measure_text = unit.measure
        return f"""      <xbrli:unit id="{_xml_escape(unit.id)}">
        <xbrli:measure>{_xml_escape(measure_text)}</xbrli:measure>
      </xbrli:unit>"""

    # ----------------------------------------------------------------
    # Hidden facts
    # ----------------------------------------------------------------

    def _render_hidden_facts(self) -> str:
        parts = []
        for fact in self._hidden_facts:
            parts.append(self._render_fact(fact, hidden=True))
        return "\n".join(parts)

    def _render_fact(self, fact: Fact, hidden: bool = False) -> str:
        indent = "      " if hidden else "  "
        ctx_ref = f'contextRef="{_xml_escape(fact.context_id)}"'

        if fact.nil:
            if fact.kind == "numeric":
                return (
                    f'{indent}<ix:nonFraction name="{_xml_escape(fact.qname)}" '
                    f'{ctx_ref} unitRef="{_xml_escape(fact.unit_id or "")}" '
                    f'decimals="{fact.decimals}" xsi:nil="true" '
                    f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>'
                )
            return (
                f'{indent}<ix:nonNumeric name="{_xml_escape(fact.qname)}" '
                f'{ctx_ref} xsi:nil="true" '
                f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>'
            )

        if fact.kind == "numeric":
            return self._render_non_fraction(fact, ctx_ref, indent)
        else:
            return self._render_non_numeric(fact, ctx_ref, indent)

    def _render_non_fraction(
        self, fact: Fact, ctx_ref: str, indent: str
    ) -> str:
        unit_ref = f'unitRef="{_xml_escape(fact.unit_id or "")}"'
        decimals = f'decimals="{fact.decimals}"'
        value = fact.value
        sign = ""
        scale = ""

        if isinstance(value, Decimal):
            # Detect sign override for negative monetary values displayed positively
            if value < 0:
                sign = ' sign="-"'
                value = abs(value)
            # Scale: if value is a whole number of thousands, use scale=3
            if value == value.to_integral_value() and abs(value) >= 1000:
                int_val = int(value)
                if int_val % 1000 == 0:
                    scale = ' scale="3"'
                    display_val = int_val // 1000
                else:
                    display_val = int_val
            else:
                display_val = value
        else:
            display_val = str(value) if value is not None else "0"

        return (
            f'{indent}<ix:nonFraction name="{_xml_escape(fact.qname)}" '
            f'{ctx_ref} {unit_ref} {decimals}{sign}{scale}>'
            f'{display_val}</ix:nonFraction>'
        )

    def _render_non_numeric(
        self, fact: Fact, ctx_ref: str, indent: str
    ) -> str:
        if isinstance(fact.value, date):
            text = fact.value.isoformat()
        elif fact.value is True:
            text = "true"
        elif fact.value is False:
            text = "false"
        else:
            text = str(fact.value) if fact.value is not None else ""
        return (
            f'{indent}<ix:nonNumeric name="{_xml_escape(fact.qname)}" '
            f'{ctx_ref}>{_xml_escape(text)}</ix:nonNumeric>'
        )

    # ----------------------------------------------------------------
    # Body (visible facts in context)
    # ----------------------------------------------------------------

    def _build_body(self) -> str:
        period = (
            f"{self.snap.period_start.year}–{self.snap.period_end.year}"
            if self.snap.period_start.year != self.snap.period_end.year
            else str(self.snap.period_end.year)
        )
        entity = _xml_escape(self.snap.entity_name)
        kvk = _xml_escape(self.snap.kvk_number)
        content = []
        if self.document:
            for text in self.document.headers:
                content.append(f"<p>{_xml_escape(text)}</p>")
            for node in self.document.nodes:
                if node.kind == "paragraph":
                    content.append(f"<p>{_xml_escape(node.text)}</p>")
                else:
                    rows = ["<tr>" + "".join(f"<td>{_xml_escape(cell)}</td>" for cell in row) + "</tr>" for row in node.rows]
                    content.append("<table>" + "".join(rows) + "</table>")
            for text in self.document.footers:
                content.append(f"<p>{_xml_escape(text)}</p>")
            content.append("<h2>Reviewed facts</h2><table><tbody>")
            for fact in self._visible_facts:
                content.append("<tr><td>" + _xml_escape(fact.qname) + "</td><td>" +
                               _xml_escape(fact.context_id) + "</td><td>" +
                               self._render_fact(fact) + "</td><td>" +
                               _xml_escape(fact.source.location) + "</td></tr>")
            content.append("</tbody></table>")
        return (f'<div id="document-body"><h1>{entity} — {_xml_escape(self.report_title)} {period}</h1>'
                f'<p>KVK-nummer: {kvk} | Boekjaar: {self.snap.period_start} t/m {self.snap.period_end}</p>'
                + "\n".join(content) + "</div>")



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xml_escape(text: str) -> str:
    """Escape XML special characters."""
    if not text:
        return ""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
