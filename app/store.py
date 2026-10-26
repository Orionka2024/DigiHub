"""Owner-scoped Supabase persistence with explicit durable SQLite demo mode.

Apply supabase_security_migration.sql before using the cloud backend.
Database failures never fall back to an in-memory success.
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


from contextvars import ContextVar
from hashlib import sha256
import sqlite3
from datetime import timezone

current_actor = ContextVar("current_actor", default=None)
read_versions = ContextVar("read_versions", default=None)


class StorageUnavailable(RuntimeError):
    pass


class StorageConflict(RuntimeError):
    pass


class WorkspaceStore:
    """Owner-scoped durable storage. Local SQLite is explicitly opt-in.

    Missing configuration and database failures never fall back to memory.
    Existing ownerless cloud filings require an operator ownership migration.
    """
    def __init__(self, local_dir=None):
        self.local_dir = Path(local_dir or os.environ["KVK_LOCAL_DATA_DIR"]) if (local_dir or os.environ.get("KVK_LOCAL_DATA_DIR")) else None
        if self.local_dir and (os.environ.get("VERCEL") or os.environ.get("PROD") == "1"):
            raise StorageUnavailable("Local demo storage is disabled in production.")
        self._snapshots, self._documents = {}, {}  # legacy test cache handles; never authoritative
        if self.local_dir:
            self.local_dir.mkdir(parents=True, exist_ok=True)
            with self._db() as db:
                db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, key TEXT, owner TEXT, body TEXT, version INTEGER, PRIMARY KEY(kind,key,owner))")

    def _actor(self):
        actor = current_actor.get()
        if not actor:
            raise PermissionError("An authenticated account is required.")
        return actor

    def _db(self):
        return sqlite3.connect(self.local_dir / "workspace.sqlite3")

    def _sb(self):
        try:
            from app.supabase_client import get_supabase
            return get_supabase()
        except Exception as exc:
            raise StorageUnavailable("Saving is unavailable. Ask the operator to configure durable storage; your work has not been saved.") from exc

    def _remember(self, kind, key, version):
        versions = dict(read_versions.get() or {})
        versions[(self._actor(), kind, key)] = version
        read_versions.set(versions)

    def _rows(self, kind, key=None):
        owner = self._actor()
        try:
            if self.local_dir:
                with self._db() as db:
                    sql = "SELECT key,body,version FROM records WHERE kind=? AND owner=?"
                    args = [kind, owner]
                    if key is not None:
                        sql += " AND key=?"; args.append(key)
                    return [(k, json.loads(b), v) for k,b,v in db.execute(sql,args)]
            table, keyfield, ownerfield, bodyfield = self._fields(kind)
            query = self._sb().table(table).select(f"{keyfield},{bodyfield},version").eq(ownerfield, owner)
            if key is not None:
                query = query.eq(keyfield, key)
            result = []
            for row in query.execute().data:
                body = row[bodyfield]
                result.append((row[keyfield], json.loads(body) if isinstance(body,str) else body, row["version"]))
            return result
        except StorageUnavailable:
            raise
        except Exception as exc:
            raise StorageUnavailable("Storage could not be read. Please retry; no cached copy has been substituted.") from exc

    @staticmethod
    def _fields(kind):
        return ("filings", "filing_id", "created_by", "snapshot") if kind == "filing" else ("workspace_documents", "sha256", "owner_id", "payload")

    def _read(self, kind, key):
        rows = self._rows(kind,key)
        if not rows:
            raise KeyError("This item does not exist or is not available to your account.")
        _, body, version = rows[0]
        self._remember(kind,key,version)
        return body

    def _write(self, kind, key, body, create=False):
        owner = self._actor()
        expected = (read_versions.get() or {}).get((owner,kind,key))
        if not create and expected is None:
            raise StorageConflict("Reload this filing before saving changes.")
        encoded = json.dumps(body, default=_default_serialiser)
        version = 1 if create else expected + 1
        try:
            if self.local_dir:
                with self._db() as db:
                    if create:
                        db.execute("INSERT INTO records VALUES (?,?,?,?,?)", (kind,key,owner,encoded,version))
                    else:
                        changed = db.execute("UPDATE records SET body=?,version=? WHERE kind=? AND key=? AND owner=? AND version=?", (encoded,version,kind,key,owner,expected)).rowcount
                        if changed != 1:
                            raise StorageConflict("Another session changed this filing. Reload before continuing.")
            else:
                table, keyfield, ownerfield, bodyfield = self._fields(kind)
                row = {bodyfield:json.loads(encoded), "version":version}
                if kind == "filing":
                    row.update({k: body[k] for k in ("kvk_number","entity_name","period_start","period_end","taxonomy_id","entry_point_key","document_sha256","state")})
                    row["updated_at"] = datetime.now(timezone.utc).isoformat()
                if create:
                    row.update({keyfield:key,ownerfield:owner})
                    self._sb().table(table).insert(row).execute()
                else:
                    result = self._sb().table(table).update(row).eq(keyfield,key).eq(ownerfield,owner).eq("version",expected).execute()
                    if not result.data:
                        raise StorageConflict("Another session changed this filing. Reload before continuing.")
        except (StorageConflict, StorageUnavailable):
            raise
        except Exception as exc:
            raise StorageUnavailable("The change could not be saved. Keep this page open and retry.") from exc
        self._remember(kind,key,version)

    def add(self, snapshot):
        self._write("filing",snapshot.filing_id,_snapshot_to_dict(snapshot),create=True)

    def get(self, filing_id):
        return _snapshot_from_dict(self._read("filing",filing_id))

    def update(self, snapshot):
        previous = self._rows("filing", snapshot.filing_id)
        if not previous:
            raise KeyError("Filing unavailable.")
        body = _snapshot_to_dict(snapshot)
        body["audit_events"] = previous[0][1].get("audit_events", []) + [{
            "actor": self._actor(), "at": datetime.now(timezone.utc).isoformat(),
            "state": snapshot.state.value, "snapshot_sha256": sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        }]
        self._write("filing",snapshot.filing_id,body)

    def all_ids(self):
        return [key for key,_,_ in self._rows("filing")]

    def add_document(self, document):
        # Identical source bytes are immutable; no overwrite is needed.
        if not self._rows("document",document.sha256):
            self._write("document",document.sha256,_document_to_dict(document),create=True)

    def get_document(self, document_sha256):
        try:
            return _document_from_dict(self._read("document",document_sha256))
        except KeyError as exc:
            raise KeyError("Source document unavailable to this account. Re-upload the same DOCX before continuing.") from exc

    def save_to_disk(self, kvk_number, filing_id):
        snap = self.get(filing_id)
        if kvk_number != snap.kvk_number or not re.fullmatch(r"[0-9]{8}",kvk_number):
            raise ValueError("Workspace KVK number must match the filing.")
        # All mutations already commit durably; verify readability before confirming.
        return True

    def load_from_disk(self, kvk_number, filing_id=None):
        if not re.fullmatch(r"[0-9]{8}",kvk_number):
            raise ValueError("KVK number must be exactly eight digits.")
        rows = [(k,b,v) for k,b,v in self._rows("filing",filing_id) if b["kvk_number"] == kvk_number]
        if not rows:
            raise FileNotFoundError("No saved filing is available to your account.")
        key,body,version = max(rows,key=lambda item:(item[1]["period_end"],item[2]))
        self._remember("filing",key,version)
        return _snapshot_from_dict(body)

    def list_filings(self):
        return [{k:body[k] for k in ("filing_id","entity_name","kvk_number","period_start","period_end","state")} for _,body,_ in self._rows("filing")]


store = WorkspaceStore()
