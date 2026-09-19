"""Supabase-backed workspace store for DigiHub.

Replaces the original JSON-file / in-memory store with durable PostgreSQL
storage via Supabase.  The public interface (add, get, update, add_document,
get_document, save_to_disk, load_from_disk) is preserved so that app/main.py
requires no changes to store call sites.

Supabase tables required (run supabase_migration.sql once):
  - filings    : one row per FilingSnapshot
  - documents  : one row per uploaded DOCX (keyed by SHA-256)

Environment variables required:
  SUPABASE_URL              — project URL from Supabase dashboard
  SUPABASE_SERVICE_ROLE_KEY — service-role key (server-side, bypasses RLS)
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from models import (
    Context, Dimension, Fact, FilingSnapshot, FilingState, SourceRef, Unit,
)
from docx_extract import ExtractedDocument, SourceNode, Run


# ── Serialisation helpers (unchanged from original) ───────────────────────────

def _default_serialiser(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


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
                "value": str(f.value) if isinstance(f.value, Decimal)
                         else f.value.isoformat() if type(f.value) is date
                         else f.value,
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
            snap.state = FilingState.DRAFT
            snap.frozen_at = snap.validation_digest = None
        else:
            snap.verify_frozen()
    return snap


def _document_to_dict(doc: ExtractedDocument) -> dict:
    return asdict(doc)


def _document_from_dict(data: dict) -> ExtractedDocument:
    nodes = tuple(
        SourceNode(
            **{**node,
               "runs": tuple(Run(**r) for r in node.get("runs", [])),
               "rows": tuple(tuple(row) for row in node.get("rows", []))}
        )
        for node in data["nodes"]
    )
    return ExtractedDocument(
        data["sha256"], nodes,
        tuple(data["headers"]),
        tuple(data["footers"]),
        tuple(data["warnings"]),
    )


# ── Store ─────────────────────────────────────────────────────────────────────

class WorkspaceStore:
    """Supabase-backed store for FilingSnapshots and ExtractedDocuments.

    Falls back gracefully to in-memory only when Supabase is not configured
    (e.g. local dev without env vars set), so that local testing still works.
    """

    def __init__(self) -> None:
        # In-memory cache — used when Supabase is unavailable and as a
        # request-scoped cache to avoid redundant round-trips within one
        # serverless invocation.
        self._snapshots: dict[str, FilingSnapshot] = {}
        self._documents: dict[str, ExtractedDocument] = {}
        self._supabase_available: bool | None = None  # None = not yet checked

    # ── internal ─────────────────────────────────────────────────────────────

    def _sb(self):
        """Return Supabase client or None if not configured."""
        if self._supabase_available is False:
            return None
        try:
            from app.supabase_client import get_supabase
            client = get_supabase()
            self._supabase_available = True
            return client
        except Exception as exc:
            if self._supabase_available is None:
                logging.warning("[Store] Supabase not available, using in-memory only: %s", exc)
            self._supabase_available = False
            return None

    # ── snapshots ─────────────────────────────────────────────────────────────

    def add(self, snapshot: FilingSnapshot) -> None:
        """Insert a new FilingSnapshot (create filing)."""
        self._snapshots[snapshot.filing_id] = snapshot
        sb = self._sb()
        if sb is None:
            return
        snap_dict = _snapshot_to_dict(snapshot)
        row = {
            "filing_id":        snapshot.filing_id,
            "kvk_number":       snapshot.kvk_number,
            "entity_name":      snapshot.entity_name,
            "period_start":     snapshot.period_start.isoformat(),
            "period_end":       snapshot.period_end.isoformat(),
            "taxonomy_id":      snapshot.taxonomy_id,
            "entry_point_key":  snapshot.entry_point_key,
            "document_sha256":  snapshot.document_sha256,
            "state":            snapshot.state.value,
            "snapshot":         json.dumps(snap_dict, default=_default_serialiser),
        }
        try:
            sb.table("filings").insert(row).execute()
        except Exception as exc:
            logging.error("[Store] Failed to insert filing %s: %s", snapshot.filing_id, exc)
            raise

    def get(self, filing_id: str) -> FilingSnapshot:
        """Fetch FilingSnapshot by ID — Supabase first, then in-memory cache."""
        sb = self._sb()
        if sb is not None:
            try:
                result = sb.table("filings").select("snapshot").eq("filing_id", filing_id).single().execute()
                snap_data = result.data["snapshot"]
                if isinstance(snap_data, str):
                    snap_data = json.loads(snap_data)
                snap = _snapshot_from_dict(snap_data)
                self._snapshots[filing_id] = snap
                return snap
            except Exception as exc:
                logging.warning("[Store] Supabase get(%s) failed: %s", filing_id, exc)
                # Fall through to in-memory cache

        if filing_id in self._snapshots:
            return self._snapshots[filing_id]

        raise KeyError(f"Filing {filing_id!r} not found. Create it first via /api/snapshot/create.")

    def update(self, snapshot: FilingSnapshot) -> None:
        """Persist mutations to an existing FilingSnapshot."""
        self._snapshots[snapshot.filing_id] = snapshot
        sb = self._sb()
        if sb is None:
            return
        snap_dict = _snapshot_to_dict(snapshot)
        try:
            sb.table("filings").update({
                "state":            snapshot.state.value,
                "entity_name":      snapshot.entity_name,
                "document_sha256":  snapshot.document_sha256,
                "entry_point_key":  snapshot.entry_point_key,
                "snapshot":         json.dumps(snap_dict, default=_default_serialiser),
                "updated_at":       datetime.utcnow().isoformat(),
            }).eq("filing_id", snapshot.filing_id).execute()
        except Exception as exc:
            logging.error("[Store] Failed to update filing %s: %s", snapshot.filing_id, exc)
            raise

    def all_ids(self) -> list[str]:
        sb = self._sb()
        if sb is not None:
            try:
                result = sb.table("filings").select("filing_id").execute()
                return [r["filing_id"] for r in result.data]
            except Exception as exc:
                logging.warning("[Store] all_ids failed: %s", exc)
        return list(self._snapshots.keys())

    # ── documents ─────────────────────────────────────────────────────────────

    def add_document(self, document: ExtractedDocument) -> None:
        """Store an ExtractedDocument (upsert — same DOCX may be re-uploaded)."""
        self._documents[document.sha256] = document
        sb = self._sb()
        if sb is None:
            return
        doc_dict = _document_to_dict(document)
        row = {
            "sha256":   document.sha256,
            "nodes":    json.dumps(doc_dict["nodes"]),
            "headers":  json.dumps(doc_dict["headers"]),
            "footers":  json.dumps(doc_dict["footers"]),
            "warnings": json.dumps(doc_dict["warnings"]),
        }
        try:
            sb.table("documents").upsert(row, on_conflict="sha256").execute()
        except Exception as exc:
            logging.error("[Store] Failed to upsert document %s: %s", document.sha256, exc)
            raise

    def get_document(self, document_sha256: str) -> ExtractedDocument:
        """Fetch ExtractedDocument by SHA-256."""
        if document_sha256 in self._documents:
            return self._documents[document_sha256]

        sb = self._sb()
        if sb is not None:
            try:
                result = sb.table("documents").select("*").eq("sha256", document_sha256).single().execute()
                row = result.data

                def _parse(v):
                    return json.loads(v) if isinstance(v, str) else v

                doc = _document_from_dict({
                    "sha256":   row["sha256"],
                    "nodes":    _parse(row["nodes"]),
                    "headers":  _parse(row["headers"]),
                    "footers":  _parse(row["footers"]),
                    "warnings": _parse(row["warnings"]),
                })
                self._documents[document_sha256] = doc
                return doc
            except Exception as exc:
                logging.warning("[Store] get_document(%s) failed: %s", document_sha256, exc)

        raise KeyError(
            "The source DOCX is not available in this session. Re-upload it before mapping or packaging."
        )

    # ── workspace save / load (compatibility) ─────────────────────────────────

    def save_to_disk(self, kvk_number: str, filing_id: str) -> Path:
        """Persist snapshot to Supabase (and optionally to /tmp as a local backup)."""
        snap = self.get(filing_id)
        if kvk_number != snap.kvk_number or not kvk_number.isdigit() or len(kvk_number) != 8:
            raise ValueError("Workspace KVK number must match the validated filing KVK number.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", filing_id):
            raise ValueError("Invalid filing ID.")
        self.update(snap)
        # Return a synthetic path (callers only log or return it as a string)
        return Path(f"/tmp/kvk_data/{kvk_number}-{snap.period_end.year}-{filing_id}.json")

    def load_from_disk(self, kvk_number: str, filing_id: str | None = None) -> FilingSnapshot:
        """Load a filing from Supabase by KVK number (and optional filing ID)."""
        if not kvk_number.isdigit() or len(kvk_number) != 8:
            raise ValueError("KVK number must be exactly eight digits.")

        sb = self._sb()
        if sb is not None:
            try:
                query = sb.table("filings").select("snapshot").eq("kvk_number", kvk_number)
                if filing_id:
                    if not re.fullmatch(r"[A-Za-z0-9_-]+", filing_id):
                        raise ValueError("Invalid filing ID.")
                    query = query.eq("filing_id", filing_id)
                result = query.order("updated_at", desc=True).limit(1).execute()
                if result.data:
                    snap_data = result.data[0]["snapshot"]
                    if isinstance(snap_data, str):
                        snap_data = json.loads(snap_data)
                    snap = _snapshot_from_dict(snap_data)
                    self._snapshots[snap.filing_id] = snap
                    return snap
            except (ValueError, re.error):
                raise
            except Exception as exc:
                logging.warning("[Store] load_from_disk(%s) failed: %s", kvk_number, exc)

        raise FileNotFoundError(f"No saved workspace for KVK {kvk_number}.")


store = WorkspaceStore()
