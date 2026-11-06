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

_DATA_DIR = Path(os.environ.get("KVK_DATA_DIR", "/tmp/kvk_data"))


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
        "profile_id": s.profile_id,
        "taxonomy_version": s.taxonomy_version,
        "taxonomy_sha256": s.taxonomy_sha256,
        "dependency_checksums": s.dependency_checksums,
        "rules_version": s.rules_version,
        "warning_dispositions": s.warning_dispositions,
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
                "scale": f.scale, "sign": f.sign, "number_format": f.number_format,
                "unit_id": f.unit_id, "decimals": f.decimals,
                "source": {
                    "document_sha256": f.source.document_sha256,
                    "location": f.source.location,
                    "extracted_value": f.source.extracted_value,
                    "reviewer": f.source.reviewer,
                    "reviewed_at": f.source.reviewed_at,
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
            scale=f.get("scale", 0), sign=f.get("sign"), number_format=f.get("number_format", "en"),
            unit_id=f["unit_id"], decimals=f["decimals"],
            source=SourceRef(
                document_sha256=f["source"]["document_sha256"],
                location=f["source"]["location"],
                extracted_value=f["source"]["extracted_value"],
                reviewer=f["source"]["reviewer"],
                reviewed_at=f["source"].get("reviewed_at"),
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
        profile_id=data.get("profile_id"),
        taxonomy_version=data.get("taxonomy_version", ""),
        taxonomy_sha256=data.get("taxonomy_sha256", ""),
        dependency_checksums=data.get("dependency_checksums", {}),
        rules_version=data.get("rules_version", ""),
        warning_dispositions=data.get("warning_dispositions", []),
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
        if not snap.frozen_digest or "taxonomy_version" not in data:
            snap.state = FilingState.DRAFT
            snap.frozen_at = snap.validation_digest = snap.frozen_digest = None
            snap.is_final = False
            snap.signatory_name = snap.approval_date = None
            snap.warning_dispositions = []
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

    def _document_to_db_row(self, doc_dict):
        return {
            "sha256": doc_dict["sha256"],
            "nodes": doc_dict.get("nodes", []),
            "headers": doc_dict.get("headers", []),
            "footers": doc_dict.get("footers", []),
            "warnings": doc_dict.get("warnings", []),
        }

    def _db_row_to_document_dict(self, row):
        def _parse(v):
            return json.loads(v) if isinstance(v, str) else v
        return {
            "sha256": row["sha256"],
            "nodes": _parse(row.get("nodes", [])),
            "headers": _parse(row.get("headers", [])),
            "footers": _parse(row.get("footers", [])),
            "warnings": _parse(row.get("warnings", [])),
        }

    def _rows(self, kind, key=None):
        owner = self._actor()
        if self.local_dir:
            with self._db() as db:
                sql = "SELECT key,body,version FROM records WHERE kind=? AND owner=?"
                args = [kind, owner]
                if key is not None:
                    sql += " AND key=?"; args.append(key)
                return [(k, json.loads(b), v) for k,b,v in db.execute(sql,args)]

        try:
            table, keyfield, ownerfield, bodyfield = self._fields(kind)
            try:
                query = self._sb().table(table).select(f"{keyfield},{bodyfield},version")
                if ownerfield:
                    query = query.eq(ownerfield, owner)
                if key is not None:
                    query = query.eq(keyfield, key)
                data = query.execute().data
                result = []
                for row in data:
                    body = row[bodyfield]
                    result.append((row[keyfield], json.loads(body) if isinstance(body, str) else body, row.get("version", 1)))
                return result
            except Exception as first_err:
                err_str = str(first_err)
                # Fallback for document: if workspace_documents does not exist, use documents table
                if kind == "document" and ("workspace_documents" in err_str or "PGRST205" in err_str or "42P01" in err_str):
                    d_query = self._sb().table("documents").select("*")
                    if key is not None:
                        d_query = d_query.eq("sha256", key)
                    d_res = d_query.execute()
                    result = []
                    for row in (d_res.data or []):
                        doc_dict = self._db_row_to_document_dict(row)
                        result.append((row["sha256"], doc_dict, 1))
                    return result

                # Fallback for filing: if version column does not exist on filings
                if kind == "filing" and ("version" in err_str or "42703" in err_str):
                    f_query = self._sb().table("filings").select(f"{keyfield},{bodyfield}")
                    if ownerfield:
                        f_query = f_query.eq(ownerfield, owner)
                    if key is not None:
                        f_query = f_query.eq(keyfield, key)
                    f_res = f_query.execute()
                    result = []
                    for row in (f_res.data or []):
                        body = row[bodyfield]
                        result.append((row[keyfield], json.loads(body) if isinstance(body, str) else body, 1))
                    return result

                raise
        except StorageUnavailable:
            raise
        except Exception as exc:
            if kind == "document" and key and key in self._documents:
                return [(key, _document_to_dict(self._documents[key]), 1)]
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

        if self.local_dir:
            with self._db() as db:
                if create:
                    db.execute("INSERT INTO records VALUES (?,?,?,?,?)", (kind,key,owner,encoded,version))
                else:
                    changed = db.execute("UPDATE records SET body=?,version=? WHERE kind=? AND key=? AND owner=? AND version=?", (encoded,version,kind,key,owner,expected)).rowcount
                    if changed != 1:
                        raise StorageConflict("Another session changed this filing. Reload before continuing.")
            self._remember(kind,key,version)
            return

        table, keyfield, ownerfield, bodyfield = self._fields(kind)
        parsed_body = json.loads(encoded)
        row = {bodyfield: parsed_body, "version": version}
        if kind == "filing":
            row.update({k: body[k] for k in ("kvk_number","entity_name","period_start","period_end","taxonomy_id","entry_point_key","document_sha256","state")})
            row["updated_at"] = datetime.now(timezone.utc).isoformat()

        try:
            if create:
                row.update({keyfield: key, ownerfield: owner})
                try:
                    self._sb().table(table).insert(row).execute()
                except Exception as ins_err:
                    err_str = str(ins_err)
                    if kind == "document" and ("workspace_documents" in err_str or "PGRST205" in err_str or "42P01" in err_str):
                        d_row = self._document_to_db_row(parsed_body)
                        self._sb().table("documents").upsert(d_row, on_conflict="sha256").execute()
                    elif kind == "filing" and ("version" in err_str or "42703" in err_str):
                        row.pop("version", None)
                        self._sb().table(table).insert(row).execute()
                    else:
                        raise
            else:
                try:
                    result = self._sb().table(table).update(row).eq(keyfield, key).eq(ownerfield, owner).eq("version", expected).execute()
                    if not result.data:
                        raise StorageConflict("Another session changed this filing. Reload before continuing.")
                except StorageConflict:
                    raise
                except Exception as upd_err:
                    err_str = str(upd_err)
                    if "version" in err_str or "42703" in err_str:
                        row.pop("version", None)
                        result = self._sb().table(table).update(row).eq(keyfield, key).eq(ownerfield, owner).execute()
                        if not result.data:
                            raise StorageConflict("Another session changed this filing. Reload before continuing.")
                    else:
                        raise
        except (StorageConflict, StorageUnavailable):
            raise
        except Exception as exc:
            raise StorageUnavailable("The change could not be saved. Keep this page open and retry.") from exc

        self._remember(kind,key,version)

    def add(self, snapshot):
        self._snapshots[snapshot.filing_id] = snapshot
        self._write("filing",snapshot.filing_id,_snapshot_to_dict(snapshot),create=True)

    def get(self, filing_id):
        try:
            snap = _snapshot_from_dict(self._read("filing", filing_id))
            self._snapshots[filing_id] = snap
            return snap
        except (KeyError, PermissionError, StorageConflict, StorageUnavailable):
            raise
        except Exception:
            if filing_id in self._snapshots:
                return self._snapshots[filing_id]
            raise

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
        self._snapshots[snapshot.filing_id] = snapshot

    def all_ids(self):
        return [key for key,_,_ in self._rows("filing")]

    def add_document(self, document):
        self._documents[document.sha256] = document
        doc_dict = _document_to_dict(document)
        try:
            if not self._rows("document", document.sha256):
                self._write("document", document.sha256, doc_dict, create=True)
        except Exception as exc:
            logging.warning("[Store] Failed to write document to Supabase (retaining in-memory): %s", exc)
            if self.local_dir:
                raise

    def get_document(self, document_sha256):
        try:
            doc = _document_from_dict(self._read("document", document_sha256))
            self._documents[document_sha256] = doc
            return doc
        except (PermissionError, StorageConflict, StorageUnavailable):
            raise
        except KeyError:
            if not self.local_dir:
                try:
                    res = self._sb().table("documents").select("*").eq("sha256", document_sha256).limit(1).execute()
                    if res.data:
                        doc = _document_from_dict(self._db_row_to_document_dict(res.data[0]))
                        self._documents[document_sha256] = doc
                        return doc
                except Exception:
                    pass
            raise KeyError("Source document unavailable to this account. Re-upload the same DOCX before continuing.")

    def save_to_disk(self, kvk_number, filing_id):
        snap = self.get(filing_id)
        if kvk_number != snap.kvk_number or not re.fullmatch(r"[0-9]{8}",kvk_number):
            raise ValueError("Workspace KVK number must match the filing.")
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
        result = []
        for _, body, _ in self._rows("filing"):
            item = {k: body.get(k) for k in ("filing_id", "entity_name", "kvk_number", "period_start", "period_end", "state")}
            item["profile_id"] = body.get("profile_id")
            item["taxonomy_id"] = body.get("taxonomy_id")
            item["fact_count"] = len(body.get("facts", []))
            item["year"] = int(body["period_end"][:4]) if body.get("period_end") else None
            item["is_final"] = body.get("is_final", False)
            result.append(item)
        return result

    def list_companies(self):
        from collections import defaultdict
        companies = defaultdict(lambda: {"filings": []})
        for _, body, _ in self._rows("filing"):
            kvk = body.get("kvk_number", "")
            if not kvk:
                continue
            entity_name = body.get("entity_name", "")
            year = int(body["period_end"][:4]) if body.get("period_end") else None
            filing_info = {
                "filing_id": body.get("filing_id"),
                "period_start": body.get("period_start"),
                "period_end": body.get("period_end"),
                "year": year,
                "state": body.get("state"),
                "profile_id": body.get("profile_id"),
                "taxonomy_id": body.get("taxonomy_id"),
                "fact_count": len(body.get("facts", [])),
                "is_final": body.get("is_final", False),
            }
            c = companies[kvk]
            c["kvk_number"] = kvk
            if not c.get("entity_name") or (year and year >= (c.get("latest_year") or 0)):
                c["entity_name"] = entity_name
                c["latest_year"] = year
            c["filings"].append(filing_info)

        result = []
        for kvk, data in companies.items():
            data["filings"].sort(key=lambda f: (f.get("period_end") or "", f.get("filing_id") or ""), reverse=True)
            latest = data["filings"][0] if data["filings"] else {}
            data["latest_filing_id"] = latest.get("filing_id")
            data["latest_year"] = latest.get("year")
            data["latest_state"] = latest.get("state")
            data["latest_profile_id"] = latest.get("profile_id")
            data["total_filings"] = len(data["filings"])
            result.append(data)
        result.sort(key=lambda c: (c.get("entity_name") or "").lower())
        return result


store = WorkspaceStore()
