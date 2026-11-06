"""Ordered DOCX extraction with immutable source provenance.

The extractor intentionally returns reviewable source nodes, not automatically
selected KVK concepts. Taxonomy mapping remains a controlled accounting decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from typing import Literal

from docx import Document
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn


@dataclass(frozen=True)
class Run:
    text: str
    bold: bool
    italic: bool


@dataclass(frozen=True)
class SourceNode:
    id: str
    kind: Literal["paragraph", "table"]
    location: str
    style: str | None
    text: str = ""
    runs: tuple[Run, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class ExtractedDocument:
    sha256: str
    nodes: tuple[SourceNode, ...]
    headers: tuple[str, ...]
    footers: tuple[str, ...]
    warnings: tuple[str, ...]


def _paragraph_node(paragraph: Paragraph, identifier: str, location: str) -> SourceNode:
    runs = tuple(Run(run.text, bool(run.bold), bool(run.italic)) for run in paragraph.runs)
    return SourceNode(identifier, "paragraph", location, paragraph.style.name if paragraph.style else None, paragraph.text, runs)


def _table_node(table: Table, identifier: str, location: str) -> SourceNode:
    # python-docx exposes merged cells more than once. Preserve text but flag it
    # for accountant review rather than inventing a semantic span.
    rows = tuple(tuple(cell.text for cell in row.cells) for row in table.rows)
    return SourceNode(identifier, "table", location, None, rows=rows)


def _header_footer_text(document: Document) -> tuple[tuple[str, ...], tuple[str, ...]]:
    headers: list[str] = []
    footers: list[str] = []
    for section in document.sections:
        headers.extend(p.text for p in section.header.paragraphs if p.text.strip())
        footers.extend(p.text for p in section.footer.paragraphs if p.text.strip())
    return tuple(headers), tuple(footers)


def extract_docx(data: bytes) -> ExtractedDocument:
    document = Document(BytesIO(data))
    nodes: list[SourceNode] = []
    paragraph_no = table_no = 0
    warnings: list[str] = []
    from zipfile import ZipFile
    from lxml import etree
    with ZipFile(BytesIO(data)) as archive:
        names = archive.namelist()
        for fragment, label in (("vbaProject", "macros"), ("word/embeddings/", "embedded objects"),
                                ("word/charts/", "charts"), ("word/diagrams/", "SmartArt")):
            if any(fragment in name for name in names):
                warnings.append(f"UNSUPPORTED_CONTENT: {label} are not preserved by this renderer.")
        for name in names:
            if name.startswith("word/") and name.endswith(".xml"):
                root = etree.fromstring(archive.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
                kinds = {etree.QName(n).localname for n in root.iter() if isinstance(n.tag, str)}
                for kind in sorted(kinds & {"drawing", "pict", "object", "altChunk", "txbxContent", "gridSpan", "vMerge", "ins", "del", "fldChar", "footnoteReference", "endnoteReference"}):
                    warnings.append(f"UNSUPPORTED_CONTENT: {kind} in {name} requires source remediation.")
                if root.xpath('//*[local-name()="tbl"]//*[local-name()="tbl"]'):
                    warnings.append(f"UNSUPPORTED_CONTENT: nested tables in {name}.")
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph_no += 1
            paragraph = Paragraph(child, document)
            nodes.append(_paragraph_node(paragraph, f"p{paragraph_no}", f"body paragraph {paragraph_no}"))
        elif child.tag == qn("w:tbl"):
            table_no += 1
            table = Table(child, document)
            nodes.append(_table_node(table, f"t{table_no}", f"body table {table_no}"))
    if document.inline_shapes:
        warnings.append(f"{len(document.inline_shapes)} inline image(s) require placement/alt-text review.")
    headers, footers = _header_footer_text(document)
    if headers or footers:
        warnings.append("Headers and footers are extracted separately and require presentation review.")
    return ExtractedDocument(sha256(data).hexdigest(), tuple(nodes), headers, footers, tuple(warnings))
