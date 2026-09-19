"""Simple JSON file-based workspace store.

Each saved workspace is written to  app/data/<kvk_number>.json  so it survives
server restarts.  The in-memory registry (`_snapshots`) is the canonical source
during a live session; the file provides persistence across sessions.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from dataclasses import asdict
from tempfile import NamedTemporaryFile
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from models import (
    Context, Dimension, Fact, FilingSnapshot, FilingState, SourceRef, Unit,
)
from docx_extract import ExtractedDocument, SourceNode, Run


# ── Helpers ────────────────────────────────────────────────────────────────────

def _default_serialiser(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


def _snapshot_to_dict(s: FilingSnapshot) -> dict:
    return {
        "filing_id": s.filing_id,
        "entity_name": s.entity_name,
        "kvk_number": s.kvk_number,
        "period_start": s.period_start.isoformat(),
        "period_end": s.period_end.isoformat(),
        "taxonomy_id": s.taxonomy_id,
        "entry_point_key": s.entry_point_key,
        "document_sha256": s.document_sha256,
        "state": s.state.value,
        "frozen_at": s.frozen_at.isoformat() if s.frozen_at else None,
        "validation_digest": s.validation_digest,
        "frozen_digest": s.frozen_digest,
        "is_final": s.is_final,
        "signatory_name": s.signatory_name,
        "approval_date": s.approval_date.isoformat() if s.approval_date else None,
        "report_sections": list(s.report_sections),
        "reviewed_requirement_ids": list(s.reviewed_requirement_ids),
        "facts": [
            {
                "id": f.id, "qname": f.qname, "context_id": f.context_id,
                "value": str(f.value) if isinstance(f.value, Decimal) else f.value.isoformat() if type(f.value) is date else f.value,
                "kind": f.kind, "nil": f.nil,
                "unit_id": f.unit_id, "decimals": f.decimals,
                "source": {
                    "document_sha256": f.source.document_sha256,
                    "location": f.source.location,
                    "extracted_value": f.source.extracted_value,
                    "reviewer": f.source.reviewer,
                },
            }
            for f in s.facts
        ],
        "contexts": [
            {
                "id": c.id, "entity_scheme": c.entity_scheme,
                "entity_identifier": c.entity_identifier,
                "instant": c.instant.isoformat() if c.instant else None,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "dimensions": [{"axis": d.axis, "member": d.member} for d in c.dimensions],
            }
            for c in s.contexts
        ],
        "units": [{"id": u.id, "measure": u.measure} for u in s.units],
    }


def _restore_value(kind, value):
    if value is None:
        return None
    if kind == "numeric":
        return Decimal(value)
    if kind == "date":
        return date.fromisoformat(value)
    if kind == "boolean":
        if type(value) is bool:
            return value
        if value in ("true", "True"):
            return True
        if value in ("false", "False"):
            return False
        raise ValueError("Invalid saved boolean value.")
    return value


def _snapshot_from_dict(data: dict) -> FilingSnapshot:
    facts = [
        Fact(
            id=f["id"], qname=f["qname"], context_id=f["context_id"],
            value=_restore_value(f["kind"], f["value"]),
            kind=f["kind"], nil=f["nil"],
            unit_id=f["unit_id"], decimals=f["decimals"],
            source=SourceRef(
                document_sha256=f["source"]["document_sha256"],
                location=f["source"]["location"],
                extracted_value=f["source"]["extracted_value"],
                reviewer=f["source"]["reviewer"],
            ),
        )
        for f in data["facts"]
    ]
    contexts = [
        Context(
            id=c["id"], entity_scheme=c["entity_scheme"],
            entity_identifier=c["entity_identifier"],
            instant=date.fromisoformat(c["instant"]) if c["instant"] else None,
            start_date=date.fromisoformat(c["start_date"]) if c["start_date"] else None,
            end_date=date.fromisoformat(c["end_date"]) if c["end_date"] else None,
            dimensions=tuple(Dimension(axis=d["axis"], member=d["member"]) for d in c["dimensions"]),
        )
        for c in data["contexts"]
    ]
    units = [Unit(id=u["id"], measure=u["measure"]) for u in data["units"]]
    snap = FilingSnapshot(
        filing_id=data["filing_id"],
        entity_name=data["entity_name"],
        kvk_number=data["kvk_number"],
        period_start=date.fromisoformat(data["period_start"]),
        period_end=date.fromisoformat(data["period_end"]),
        taxonomy_id=data["taxonomy_id"],
        entry_point_key=data["entry_point_key"],
        document_sha256=data["document_sha256"],
        report_sections=set(data.get("report_sections", [])),
        reviewed_requirement_ids=set(data.get("reviewed_requirement_ids", [])),
        facts=facts,
        contexts=contexts,
        units=units,
        state=FilingState(data["state"]),
        frozen_at=datetime.fromisoformat(data["frozen_at"]) if data.get("frozen_at") else None,
        validation_digest=data.get("validation_digest"),
        frozen_digest=data.get("frozen_digest"),
        is_final=data.get("is_final", False),
        signatory_name=data.get("signatory_name"),
        approval_date=date.fromisoformat(data["approval_date"]) if data.get("approval_date") else None,
    )
    if snap.state in (FilingState.FROZEN, FilingState.VALIDATED):
        if not snap.frozen_digest:
            # Old saves did not bind validation to content; require a new review.
            snap.state = FilingState.DRAFT
            snap.frozen_at = snap.validation_digest = None
        else:
            snap.verify_frozen()
    return snap


# ── Store ──────────────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent / "data"


class WorkspaceStore:
    """In-memory registry of FilingSnapshots, with optional JSON file persistence."""

    def __init__(self) -> None:
        self._snapshots: dict[str, FilingSnapshot] = {}  # keyed by filing_id
        self._documents: dict[str, ExtractedDocument] = {}  # keyed by source SHA-256
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # -- in-memory access --

    def add(self, snapshot: FilingSnapshot) -> None:
        self._snapshots[snapshot.filing_id] = snapshot

    def get(self, filing_id: str) -> FilingSnapshot:
        try:
            return self._snapshots[filing_id]
        except KeyError:
            raise KeyError(f"Filing {filing_id!r} not found. Create it first via /api/snapshot/create.")

    def all_ids(self) -> list[str]:
        return list(self._snapshots.keys())

    def add_document(self, document: ExtractedDocument) -> None:
        self._documents[document.sha256] = document

    def get_document(self, document_sha256: str) -> ExtractedDocument:
        try:
            return self._documents[document_sha256]
        except KeyError:
            raise KeyError("The source DOCX is not available in this session. Re-upload it before mapping or packaging.")

    # -- persistence --

    def save_to_disk(self, kvk_number: str, filing_id: str) -> Path:
        snapshot = self.get(filing_id)
        if kvk_number != snapshot.kvk_number or not kvk_number.isdigit() or len(kvk_number) != 8:
            raise ValueError("Workspace KVK number must match the validated filing KVK number.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", filing_id):
            raise ValueError("Invalid filing ID.")
        path = _DATA_DIR / f"{kvk_number}-{snapshot.period_end.year}-{filing_id}.json"
        document = self._documents.get(snapshot.document_sha256)
        data = {"schema_version": 2, "kvk_number": kvk_number, "filing_id": filing_id,
                "saved_at": datetime.now().isoformat(), "snapshot": _snapshot_to_dict(snapshot),
                "document": asdict(document) if document else None}
        with NamedTemporaryFile("w", encoding="utf-8", dir=_DATA_DIR, suffix=".tmp", delete=False) as fh:
            temp = Path(fh.name)
            try:
                json.dump(data, fh, default=_default_serialiser, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
        try:
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return path

    def load_from_disk(self, kvk_number: str, filing_id: str | None = None) -> FilingSnapshot:
        if not kvk_number.isdigit() or len(kvk_number) != 8:
            raise ValueError("KVK number must be exactly eight digits.")
        paths = list(_DATA_DIR.glob(f"{kvk_number}-*.json"))
        legacy = _DATA_DIR / f"{kvk_number}.json"
        if legacy.exists():
            paths.append(legacy)
        if filing_id:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", filing_id):
                raise ValueError("Invalid filing ID.")
            paths = [p for p in paths if p.name.endswith(f"-{filing_id}.json")]
        path = max(paths, key=lambda p: p.stat().st_mtime_ns) if paths else legacy
        if not path.exists():
            raise FileNotFoundError(f"No saved workspace for KVK {kvk_number}.")
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        snapshot = _snapshot_from_dict(data["snapshot"])
        saved_doc = data.get("document")
        if saved_doc:
            nodes = tuple(SourceNode(**{**node, "runs": tuple(Run(**r) for r in node.get("runs", [])),
                                       "rows": tuple(tuple(row) for row in node.get("rows", []))})
                          for node in saved_doc["nodes"])
            document = ExtractedDocument(saved_doc["sha256"], nodes, tuple(saved_doc["headers"]),
                                         tuple(saved_doc["footers"]), tuple(saved_doc["warnings"]))
            if document.sha256 != snapshot.document_sha256:
                raise ValueError("Saved source identity does not match the filing.")
            self.add_document(document)
        self._snapshots[snapshot.filing_id] = snapshot
        return snapshot


store = WorkspaceStore()
