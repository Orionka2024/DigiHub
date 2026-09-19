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
