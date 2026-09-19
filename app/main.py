"""KVK iXBRL v2 – FastAPI application.

Launch via the start.sh script, which sets PYTHONPATH correctly:
    bash KVK_v2/app/start.sh

Or manually from /Users/aleksandrkim/Documents:
    PYTHONPATH=. uvicorn KVK_v2.app.main:app --reload --port 8000
"""
from __future__ import annotations

import io
import hashlib
import json
import os
import uuid
from datetime import datetime, date, timezone
from dataclasses import asdict, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

# Core KVK_v2 library — uses relative imports internally, so we must import
# via the package path (KVK_v2.xxx) when PYTHONPATH=/Users/.../Documents
from docx_extract import extract_docx
from mapping import MappingDecision, fact_from_decision
from autotagger import recommend_tags
from models import Context, Dimension, FilingSnapshot, FilingState, Unit
from registry import TaggingRequirement, TaxonomyRelease, TaxonomyRegistry
from service import ExportBlocked, FilingService, configured_external_validator
from validator import ValidationIssue, validate_snapshot, validate_xml
from app.models_api import (
    AddSectionIn, ContextIn, DimensionIn, ExtractedDocumentOut,
    KvkLookupOut, MapFactIn, MapFactOut, MappingDecisionIn,
    ReviewRequirementIn, RunOut, SnapshotCreateIn, SnapshotOut,
    SourceNodeOut, TaxonomyReleaseIn, ValidateOut, ValidationIssueOut,
    WorkspaceOut, WorkspaceSaveIn, FreezeIn, AutoTagRequest, AutoTagResponse
)
from app.store import store

# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="KVK iXBRL v2 Filing Platform", version="2.0.0")

# ── CORS ─────────────────────────────────────────────────────────────────────
# Locked to localhost only. This is a local development tool; cross-origin
# access from arbitrary origins is not appropriate even in development.
# To allow a specific remote front-end, set ALLOWED_ORIGIN in the environment.
_ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://localhost:8000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        _ALLOWED_ORIGIN,
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS", "PUT", "PATCH"],
    allow_headers=["*"],
)

from app.auth import auth_router, get_current_user
app.include_router(auth_router)

@app.middleware("http")
async def auth_middleware(request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in ["/api/login", "/api/logout"]:
        from fastapi import HTTPException
        from fastapi.responses import JSONResponse
        try:
            get_current_user(request)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
            
    if path == "/":
        from fastapi import HTTPException
        from fastapi.responses import RedirectResponse
        try:
            get_current_user(request)
        except HTTPException:
            return RedirectResponse(url="/login.html")
            
    return await call_next(request)


# ── Root page ──────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Serve the workspace. Auth middleware already redirects unauthenticated requests."""
    from fastapi.responses import HTMLResponse
    index_path = Path(__file__).parent / "frontend" / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))

# ── Taxonomy registry ──────────────────────────────────────────────────────────

taxonomy_registry = TaxonomyRegistry()

_TAXONOMY_DIR = Path(os.environ.get("KVK_TAXONOMY_DIR", str(Path(__file__).parent / "data" / "taxonomies")))


_ep_loading_status: dict[str, str] = {}
_taxonomy_errors: list[str] = []


def _parse_release_ep(release, ep_key):
    from taxonomy_parser import TaxonomyParser
    from taxonomy.rules import RulesEngine
    from copy import deepcopy
    status_key = f"{release.id}:{ep_key}"
    _ep_loading_status[status_key] = "loading"
    try:
        package = Path(release.package_path)
        catalog = package / "META-INF" / "catalog.xml"
        parser = TaxonomyParser(package, catalog if catalog.exists() else None, strict=False)
        concepts, rules = parser.parse_entry_point(release.entry_points[ep_key], ep_key, release.version)
        if not concepts:
            raise ValueError("Entry point contains no concepts.")
        merged = deepcopy(release.concepts)
        for qname, concept in concepts.items():
            if qname in merged:
                concept.entry_points = sorted(set(concept.entry_points) | set(merged[qname].entry_points))
            merged[qname] = concept
        engine = deepcopy(release.rules_engine) if release.rules_engine else RulesEngine()
        for rule in rules:
            engine.add_rule(rule)
        namespaces = dict(release.namespaces)
        for uri, prefix in parser.ns_uri_to_prefix.items():
            if prefix in namespaces and namespaces[prefix] != uri:
                raise ValueError(f"Conflicting namespace prefix: {prefix}")
            namespaces[prefix] = uri
        release.taxonomy_files = sorted(parser._visited)
        release.concepts = merged
        release.rules_engine = engine
        release.namespaces = namespaces
        _ep_loading_status[status_key] = "incomplete" if parser.errors else "done"
        if not parser.errors:
            release.complete_entry_points.add(ep_key)
        if parser.errors:
            _taxonomy_errors.append(f"{status_key}: {len(parser.errors)} unresolved dependencies; " + "; ".join(parser.errors[:3]))
    except Exception as exc:
        _ep_loading_status[status_key] = "error"
        _taxonomy_errors.append(f"{status_key}: {exc}")


def _load_verified_taxonomies() -> None:
    from registry import EnrichedTaxonomyRelease
    from taxonomy.rules import RulesEngine
    for manifest_path in _TAXONOMY_DIR.glob("*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            # A beta cannot become final by relabelling its manifest.
            if str(manifest.get("version", "")).lower().endswith((".b", ".a")):
                manifest["status"] = "beta"
            package = (manifest_path.parent / manifest["package_file"]).resolve()
            if not package.is_relative_to(_TAXONOMY_DIR.resolve()) or not package.exists():
                raise ValueError("Package must exist inside the configured taxonomy directory.")
            eps = {key: value if isinstance(value, str) else value["file"]
                   for key, value in manifest["entry_points"].items()}
            verified = package.is_file()
            digest = ""
            if verified:
                from taxonomy_package import extract_verified
                digest = manifest.get("sha256", "")
                
                # Extract to /tmp/taxonomy_extracted on Vercel since /var/task is read-only
                import os
                extraction_base = Path("/tmp/taxonomy_extracted") if os.environ.get("VERCEL") else (_TAXONOMY_DIR / ".extracted")
                package = extract_verified(package, digest, extraction_base)
            if package.is_dir():
                # Directories are useful for browsing, but are never checksum-verified releases.
                release = EnrichedTaxonomyRelease(
                    id=manifest["id"], status=manifest["status"], version=manifest.get("version", ""),
                    name=manifest.get("name", manifest["id"]), authority=manifest.get("authority", "KVK"),
                    publication_date=manifest.get("publication_date", ""), reporting_year=manifest.get("reporting_year", 0),
                    reporting_date=manifest.get("reporting_date", ""), sha256=digest, package_verified=verified,
                    package_path=str(package), entry_points=eps,
                    entry_point_meta={key: value for key, value in manifest["entry_points"].items() if isinstance(value, dict)},
                    namespaces=manifest.get("namespaces", {}), rules_engine=RulesEngine())
                requirements = tuple(TaggingRequirement(**item) for item in manifest.get("requirements", []))
                release.requirements = {key: requirements for key in eps}
                if verified and release.status == "final":
                    taxonomy_registry.register(release)
                else:
                    # A checksum proves archive integrity, not official final status.
                    release.package_verified = False
                    taxonomy_registry.register_preview(release)
                for key in eps:
                    _ep_loading_status[f"{release.id}:{key}"] = "pending"
        except Exception as exc:
            _taxonomy_errors.append(f"{manifest_path.name}: {exc}")


_load_verified_taxonomies()
filing_service = FilingService(taxonomy_registry, configured_external_validator())


from queue import Queue
_ep_queue = Queue()


def _schedule_entry_point(release, key):
    status_key = f"{release.id}:{key}"
    status = _ep_loading_status.get(status_key)
    if status in {"done", "incomplete"}:
        return
    if status != "loading":
        _parse_release_ep(release, key)


def _load_remaining_entry_points() -> None:
    import threading
    def load():
        while True:
            release, key = _ep_queue.get()
            try:
                _parse_release_ep(release, key)
            finally:
                _ep_queue.task_done()
    if taxonomy_registry.list_all():
        threading.Thread(target=load, daemon=True, name="taxonomy-bg-loader").start()
        for release in taxonomy_registry.list_all():
            if getattr(release, "package_path", None) and release.entry_points:
                _schedule_entry_point(release, next(iter(release.entry_points)))


_load_remaining_entry_points()


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    """Health check. Exposes taxonomy registry status so operators know
    whether official taxonomy packages are loaded before accepting filings."""
    registered = list(taxonomy_registry._releases.keys())  # noqa: SLF001
    return {
        "status": "ok",
        "version": "2.0.0",
        "taxonomy_count": len(registered),
        "taxonomies": registered,
        "taxonomy_ready": any(r.package_verified and taxonomy_registry.is_active(r.id) for r in taxonomy_registry.list_all()),
        "export_ready": (filing_service.external_validator is not None
                         and getattr(filing_service.external_validator, "filing_approval", True)
                         and any(r.package_verified and taxonomy_registry.is_active(r.id)
                                 and (not hasattr(r, "complete_entry_points") or r.complete_entry_points)
                                 for r in taxonomy_registry.list_all())),
        "entry_point_status": dict(_ep_loading_status),
        "errors": list(_taxonomy_errors),
        "warning": (
            None if any(r.package_verified for r in taxonomy_registry.list_all())
            else "No verified taxonomy packages are loaded. "
                 "Place a manifest + package file in app/data/taxonomies/ to enable validation."
        ),
    }


# ── Taxonomy endpoints ─────────────────────────────────────────────────────────

from registry import EnrichedTaxonomyRelease
from app.models_api import (
    EnrichedTaxonomyReleaseOut, ConceptMetadataOut, ValidationRuleOut,
    ChecklistSectionOut, ChecklistItemOut, SelectEntryPointOut
)

@app.post("/api/taxonomy/install", status_code=201)
async def install_taxonomy() -> dict:
    raise HTTPException(status_code=501, detail="Not implemented yet")


@app.get("/api/admin/taxonomies")
async def list_admin_taxonomies() -> dict:
    releases = []
    for rel in taxonomy_registry.list_all():
        if isinstance(rel, EnrichedTaxonomyRelease):
            releases.append(EnrichedTaxonomyReleaseOut(
                id=rel.id,
                status=rel.status,
                version=rel.version,
                name=rel.name,
                authority=rel.authority,
                publication_date=rel.publication_date,
                reporting_year=rel.reporting_year,
                reporting_date=rel.reporting_date,
                sha256=rel.sha256,
                package_verified=rel.package_verified,
                is_active=taxonomy_registry.is_active(rel.id),
                entry_point_count=len(rel.entry_points),
                concept_count=len(rel.concepts)
            ))
        else:
            # Fallback for legacy TaxonomyRelease
            releases.append(EnrichedTaxonomyReleaseOut(
                id=rel.id, status=rel.status, version="unknown", name=rel.id,
                authority="unknown", publication_date="", reporting_year=0,
                reporting_date="", sha256=rel.sha256, package_verified=rel.package_verified,
                is_active=taxonomy_registry.is_active(rel.id),
                entry_point_count=len(rel.entry_points), concept_count=0
            ))
    return {"taxonomies": releases}

@app.post("/api/admin/taxonomy/{taxonomy_id}/activate")
async def activate_taxonomy(taxonomy_id: str) -> dict:
    try:
        taxonomy_registry.activate(taxonomy_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.post("/api/admin/taxonomy/{taxonomy_id}/deactivate")
async def deactivate_taxonomy(taxonomy_id: str) -> dict:
    try:
        taxonomy_registry.deactivate(taxonomy_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/admin/taxonomy/{taxonomy_id}/namespaces")
async def get_taxonomy_namespaces(taxonomy_id: str) -> dict:
    try:
        rel = taxonomy_registry.get(taxonomy_id)
        return {"namespaces": rel.namespaces}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/admin/taxonomy/{taxonomy_id}/files")
async def get_taxonomy_files(taxonomy_id: str) -> dict:
    try:
        rel = taxonomy_registry.get_enriched(taxonomy_id)
        return {"files": rel.taxonomy_files}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/taxonomy/list")
async def list_taxonomies() -> dict:
    ids = list(taxonomy_registry._releases.keys())  # noqa: SLF001
    return {"taxonomies": ids}

@app.get("/api/taxonomy/{taxonomy_id}/entry-points/select", response_model=SelectEntryPointOut)
async def select_entry_point(taxonomy_id: str, company_class: str = "groot", sector: str = "general", framework: str = "nlgaap", consolidated: bool = True) -> SelectEntryPointOut:
    try:
        rel = taxonomy_registry.get_enriched(taxonomy_id)
        ep = rel.select_entry_point(company_class, sector, framework, consolidated)
        return SelectEntryPointOut(entry_point_key=ep)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/taxonomy/{taxonomy_id}/entry-points")
async def get_entry_points(taxonomy_id: str) -> dict:
    try:
        rel = taxonomy_registry.get(taxonomy_id)
        return {"entry_points": rel.entry_points,
                "metadata": {key: asdict(value) for key, value in getattr(rel, "entry_point_meta", {}).items()}}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/taxonomy/{taxonomy_id}/concepts")
async def get_concepts(taxonomy_id: str, entry_point_key: str = "") -> dict:
    try:
        rel = taxonomy_registry.get_enriched(taxonomy_id)
        if entry_point_key:
            if entry_point_key not in rel.entry_points:
                raise ValueError("Unknown entry point.")
            _schedule_entry_point(rel, entry_point_key)
            if _ep_loading_status.get(f"{taxonomy_id}:{entry_point_key}") == "error":
                raise HTTPException(status_code=422, detail="Entry point failed to load. See /health for details.")
            if _ep_loading_status.get(f"{taxonomy_id}:{entry_point_key}") in {"pending", "queued", "loading"}:
                raise HTTPException(status_code=503, detail="Entry point is loading or unavailable. See /health.")
            concepts = rel.get_concepts_for_ep(entry_point_key, exclude_abstract=False)
        else:
            concepts = list(rel.concepts.values())
        return {"concepts": [
            ConceptMetadataOut(
                qname=c.qname, namespace=c.namespace, local_name=c.local_name,
                label_nl=c.label_nl, label_en=c.label_en, documentation=c.documentation,
                data_type=c.data_type, period_type=c.period_type, balance=c.balance,
                abstract=c.abstract, nillable=c.nillable, mandatory_status=c.mandatory_status,
                rule_ids=c.rule_ids, condition_nl=c.condition_nl
            ) for c in concepts
        ]}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/taxonomy/{taxonomy_id}/concepts/{qname:path}")
async def get_concept(taxonomy_id: str, qname: str) -> ConceptMetadataOut:
    try:
        rel = taxonomy_registry.get_enriched(taxonomy_id)
        c = rel.get_concept(qname)
        if not c:
            raise HTTPException(status_code=404, detail="Concept not found")
        return ConceptMetadataOut(
            qname=c.qname, namespace=c.namespace, local_name=c.local_name,
            label_nl=c.label_nl, label_en=c.label_en, documentation=c.documentation,
            data_type=c.data_type, period_type=c.period_type, balance=c.balance,
            abstract=c.abstract, nillable=c.nillable, mandatory_status=c.mandatory_status,
            rule_ids=c.rule_ids, condition_nl=c.condition_nl
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/taxonomy/{taxonomy_id}/rules")
async def get_rules(taxonomy_id: str) -> dict:
    try:
        rel = taxonomy_registry.get_enriched(taxonomy_id)
        if not rel.rules_engine:
            return {"rules": []}
        return {"rules": [
            ValidationRuleOut(
                rule_id=r.rule_id, rule_type=r.rule_type, status=r.status,
                concept_qname=r.concept_qname, condition_nl=r.condition_nl,
                error_message_nl=r.error_message_nl, entry_points=list(r.entry_points)
            ) for r in rel.rules_engine.get_all_rules()
        ]}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/taxonomy/{taxonomy_id}/checklist", response_model=list[ChecklistSectionOut])
async def get_checklist(taxonomy_id: str, entry_point_key: str, filing_id: str = "") -> list[ChecklistSectionOut]:
    try:
        rel = taxonomy_registry.get_enriched(taxonomy_id)
        snap = None
        if filing_id:
            try:
                snap = store.get(filing_id)
            except KeyError:
                pass
        
        if entry_point_key not in rel.entry_points:
            raise ValueError("Unknown entry point.")
        _schedule_entry_point(rel, entry_point_key)
        if _ep_loading_status.get(f"{taxonomy_id}:{entry_point_key}") == "error":
            raise HTTPException(status_code=422, detail="Entry point failed to load. See /health for details.")
        if _ep_loading_status.get(f"{taxonomy_id}:{entry_point_key}") in {"pending", "queued", "loading"}:
            raise HTTPException(status_code=503, detail="Entry point is not available yet; inspect /health for loading errors.")
        sections = rel.build_checklist(entry_point_key, snapshot=snap)
        out = []
        for s in sections:
            out.append(ChecklistSectionOut(
                section_id=s.section_id, title_nl=s.title_nl, title_en=s.title_en,
                total=s.total, satisfied=s.satisfied, mandatory_count=s.mandatory_count,
                conditional_count=s.conditional_count,
                items=[
                    ChecklistItemOut(
                        concept_qname=i.concept_qname, label_nl=i.label_nl, label_en=i.label_en,
                        data_type=i.data_type, period_type=i.period_type, balance=i.balance,
                        status=i.status, condition_nl=i.condition_nl, rule_ids=i.rule_ids,
                        is_satisfied=i.is_satisfied, fact_value=i.fact_value
                    ) for i in s.items
                ]
            ))
        return out
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/taxonomy/{taxonomy_id}/requirements/{entry_point_key}")
async def get_requirements(taxonomy_id: str, entry_point_key: str) -> dict:
    # Kept for backward compatibility
    try:
        rel = taxonomy_registry.get(taxonomy_id)
        if entry_point_key not in rel.requirements:
            raise ValueError(f"Unknown entry point '{entry_point_key}' for taxonomy '{taxonomy_id}'")
            
        reqs = []
        for r in rel.requirements[entry_point_key]:
            reqs.append({
                "id": r.id,
                "qname": r.qname,
                "section": r.section,
                "conditional": r.conditional
            })
        return {"requirements": reqs}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Document extraction ────────────────────────────────────────────────────────

@app.post("/api/extract", response_model=ExtractedDocumentOut)
async def extract(file: UploadFile = File(...)) -> ExtractedDocumentOut:
    """Upload a .docx file.  Returns the structured ExtractedDocument."""
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported.")
    try:
        data = await file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="DOCX exceeds the 20 MB upload limit.")
        import zipfile
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Expanded DOCX exceeds the 100 MB limit.")
        doc = extract_docx(data)
        store.add_document(doc)
        return ExtractedDocumentOut(
            sha256=doc.sha256,
            nodes=[
                SourceNodeOut(
                    id=n.id, kind=n.kind, location=n.location, style=n.style,
                    text=n.text,
                    runs=[RunOut(text=r.text, bold=r.bold, italic=r.italic) for r in n.runs],
                    rows=[list(row) for row in n.rows],
                )
                for n in doc.nodes
            ],
            headers=list(doc.headers),
            footers=list(doc.footers),
            warnings=list(doc.warnings),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot extract this DOCX: {exc}")


# ── Snapshot lifecycle ─────────────────────────────────────────────────────────

def _snap_out(snap: FilingSnapshot, warnings: list[str] | None = None) -> SnapshotOut:
    from app.store import _snapshot_to_dict
    saved = _snapshot_to_dict(snap)
    try:
        doc = store.get_document(snap.document_sha256)
        document = ExtractedDocumentOut(**asdict(doc))
    except KeyError:
        document = None
    return SnapshotOut(
        facts=saved["facts"], contexts=saved["contexts"], units=saved["units"], document=document,
        is_final=snap.is_final, signatory_name=snap.signatory_name, approval_date=snap.approval_date,
        filing_id=snap.filing_id,
        entity_name=snap.entity_name,
        kvk_number=snap.kvk_number,
        period_start=snap.period_start,
        period_end=snap.period_end,
        taxonomy_id=snap.taxonomy_id,
        entry_point_key=snap.entry_point_key,
        document_sha256=snap.document_sha256,
        state=snap.state.value,
        fact_count=len(snap.facts),
        context_count=len(snap.contexts),
        unit_count=len(snap.units),
        report_sections=list(snap.report_sections),
        reviewed_requirement_ids=list(snap.reviewed_requirement_ids),
        warnings=warnings or [],
    )


@app.post("/api/snapshot/create", response_model=SnapshotOut, status_code=201)
async def create_snapshot(payload: SnapshotCreateIn) -> SnapshotOut:
    """Create a new empty FilingSnapshot from entity metadata and document hash."""
    filing_id = str(uuid.uuid4())
    try:
        release = taxonomy_registry.get(payload.taxonomy_id)
        if payload.entry_point_key not in release.entry_points:
            raise ValueError("Unknown taxonomy entry point.")
        store.get_document(payload.document_sha256)
        snap = FilingSnapshot(
            filing_id=filing_id,
            entity_name=payload.entity_name,
            kvk_number=payload.kvk_number,
            period_start=payload.period_start,
            period_end=payload.period_end,
            taxonomy_id=payload.taxonomy_id,
            entry_point_key=payload.entry_point_key,
            document_sha256=payload.document_sha256,
        )
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    store.add(snap)
    return _snap_out(snap)


@app.get("/api/snapshot/{filing_id}", response_model=SnapshotOut)
async def get_snapshot(filing_id: str) -> SnapshotOut:
    try:
        snap = store.get(filing_id)
        return _snap_out(snap)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/snapshot/{filing_id}/map", response_model=MapFactOut)
async def map_fact(filing_id: str, payload: MapFactIn) -> MapFactOut:
    """Apply one MappingDecision to the snapshot.

    Optionally include a `context` and/or `unit` in the payload to auto-register
    them alongside the fact.
    """
    try:
        snap = store.get(filing_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if snap.state not in (FilingState.DRAFT, FilingState.REVIEWED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot map facts on a snapshot in state {snap.state.value!r}.",
        )

    try:
        contexts, units = list(snap.contexts), list(snap.units)
        if payload.context is not None:
            c = payload.context
            new_ctx = Context(id=c.id, entity_scheme=c.entity_scheme, entity_identifier=c.entity_identifier,
                              instant=c.instant, start_date=c.start_date, end_date=c.end_date,
                              dimensions=tuple(Dimension(axis=d.axis, member=d.member) for d in c.dimensions))
            existing = next((cx for cx in contexts if cx.id == new_ctx.id), None)
            if existing and existing != new_ctx:
                raise ValueError("Context ID already has different contents.")
            if not existing:
                contexts.append(new_ctx)
        if payload.unit is not None:
            new_unit = Unit(payload.unit.id, payload.unit.measure)
            existing = next((u for u in units if u.id == new_unit.id), None)
            if existing and existing != new_unit:
                raise ValueError("Unit ID already has a different measure.")
            if not existing:
                units.append(new_unit)
        source_document = store.get_document(snap.document_sha256)
        d = payload.decision
        value = Decimal(str(d.value)) if d.kind == "numeric" and d.value is not None else d.value
        fact = fact_from_decision(source_document, MappingDecision(
            source_node_id=d.source_node_id, source_location=d.source_location, qname=d.qname,
            context_id=d.context_id, kind=d.kind, value=value, unit_id=d.unit_id,
            decimals=d.decimals, reviewer=d.reviewer))
        if any(c.entity_identifier != snap.kvk_number or c.entity_scheme != "http://www.kvk.nl/kvk-id" for c in contexts):
            raise ValueError("Context entity must match the filing.")
        if fact.context_id not in {c.id for c in contexts}:
            raise ValueError("Unknown context ID.")
        if fact.unit_id and fact.unit_id not in {u.id for u in units}:
            raise ValueError("Unknown unit ID.")
        if payload.replaces_fact_id and not any(f.id == payload.replaces_fact_id for f in snap.facts):
            raise ValueError("The mapping being edited no longer exists. Reload the filing.")
        replaced_ids = {fact.id, payload.replaces_fact_id}
        snap.contexts, snap.units = contexts, units
        snap.facts = [f for f in snap.facts if f.id not in replaced_ids] + [fact]
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return MapFactOut(fact_id=fact.id, qname=fact.qname)


@app.post("/api/snapshot/{filing_id}/auto-tag-table", response_model=AutoTagResponse)
async def auto_tag_table(filing_id: str, payload: AutoTagRequest) -> AutoTagResponse:
    try:
        snap = store.get(filing_id)
        document = store.get_document(snap.document_sha256)
        taxonomy = taxonomy_registry.get(snap.taxonomy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
        
    node = next((n for n in document.nodes if n.id == payload.source_node_id), None)
    if not node or node.kind != "table":
        raise HTTPException(status_code=400, detail="Invalid table node ID")
        
    # Using EnrichedTaxonomyRelease
    if hasattr(taxonomy, "rules_engine"):
        _schedule_entry_point(taxonomy, snap.entry_point_key)
        if _ep_loading_status.get(f"{taxonomy.id}:{snap.entry_point_key}") in {"pending", "queued", "loading", "error"}:
            raise HTTPException(status_code=503, detail="Selected taxonomy concepts are not available yet.")
        concepts = taxonomy.get_concepts_for_ep(snap.entry_point_key)
        # We only care about monetary/numeric concepts
        requirements = [c for c in concepts if c.is_numeric()]
    else:
        requirements = taxonomy.requirements.get(snap.entry_point_key, [])
        
    recommendations = recommend_tags(node, requirements)
    mapped_locations = {fact.source.location for fact in snap.facts}
    recommendations = [rec for rec in recommendations if rec["source_location"] not in mapped_locations]
    
    return AutoTagResponse(recommendations=recommendations)


@app.delete("/api/snapshot/{filing_id}/facts/{fact_id}")
async def remove_fact(filing_id: str, fact_id: str) -> dict:
    """Remove a previously mapped fact from the snapshot."""
    try:
        snap = store.get(filing_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if snap.state not in (FilingState.DRAFT, FilingState.REVIEWED):
        raise HTTPException(status_code=409, detail="Cannot modify a frozen/validated snapshot.")

    before = len(snap.facts)
    snap.facts = [f for f in snap.facts if f.id != fact_id]
    return {"removed": before - len(snap.facts)}


@app.post("/api/snapshot/{filing_id}/sections")
async def add_section(filing_id: str, payload: AddSectionIn) -> dict:
    """Mark a report section as present."""
    try:
        snap = store.get(filing_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if snap.state not in (FilingState.DRAFT, FilingState.REVIEWED):
        raise HTTPException(status_code=409, detail="Cannot modify a frozen/validated snapshot.")
    snap.report_sections.add(payload.section)
    return {"sections": list(snap.report_sections)}


@app.post("/api/snapshot/{filing_id}/review-requirement")
async def review_requirement(filing_id: str, payload: ReviewRequirementIn) -> dict:
    """Mark a conditional tagging requirement as reviewed."""
    try:
        snap = store.get(filing_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if snap.state not in (FilingState.DRAFT, FilingState.REVIEWED):
        raise HTTPException(status_code=409, detail="Cannot modify a frozen/validated snapshot.")
    snap.reviewed_requirement_ids.add(payload.requirement_id)
    return {"reviewed": list(snap.reviewed_requirement_ids)}


@app.post("/api/snapshot/{filing_id}/freeze", response_model=SnapshotOut)
async def freeze_snapshot(filing_id: str, payload: FreezeIn) -> SnapshotOut:
    """Freeze the snapshot.  Required before validate-and-package."""
    try:
        snap = store.get(filing_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        taxonomy = taxonomy_registry.get(snap.taxonomy_id)
        candidate = replace(snap, is_final=payload.is_final, signatory_name=payload.signatory_name, approval_date=payload.approval_date)
        issues = validate_snapshot(candidate, taxonomy)
        critical_issues = [i for i in issues if i.severity in {'error', 'critical'}]
        if critical_issues:
            raise ValueError("Validation must pass before freeze: " + "; ".join(i.code for i in critical_issues))
        store.get_document(snap.document_sha256)
        snap.freeze(is_final=payload.is_final, signatory_name=payload.signatory_name, approval_date=payload.approval_date)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _snap_out(snap)


@app.post("/api/snapshot/{filing_id}/reopen", response_model=SnapshotOut)
async def reopen_snapshot(filing_id: str) -> SnapshotOut:
    try:
        snap = store.get(filing_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    snap.state = FilingState.DRAFT
    snap.frozen_at = snap.frozen_digest = snap.validation_digest = None
    snap.is_final = False
    snap.signatory_name = snap.approval_date = None
    return _snap_out(snap)


@app.post("/api/snapshot/{filing_id}/validate", response_model=ValidateOut)
async def validate_only(filing_id: str) -> ValidateOut:
    """Run validation without generating the package.  Useful for Diagnostics."""
    try:
        snap = store.get(filing_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        taxonomy = taxonomy_registry.get(snap.taxonomy_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    issues = validate_snapshot(snap, taxonomy)
    if not taxonomy.package_verified:
        issues.append(ValidationIssue("TAXONOMY_UNVERIFIED", "This taxonomy is available for preparation only; its package is not verified."))
    if filing_service.external_validator is None:
        issues.append(ValidationIssue("VALIDATION_INCOMPLETE", "Independent DTS, formula and filing-rule validation is not configured."))
    return ValidateOut(
        ok=len(issues) == 0,
        issues=[ValidationIssueOut(**asdict(i)) for i in issues],
    )


@app.post("/api/snapshot/{filing_id}/validate-and-package")
async def validate_and_package(filing_id: str) -> StreamingResponse:
    """Validate the frozen snapshot and return an SBR report package ZIP."""
    try:
        snap = store.get(filing_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        document = store.get_document(snap.document_sha256)
        zip_bytes = filing_service.validate_and_package(snap, document)
    except ExportBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    filename = f"report_{snap.kvk_number}_{snap.period_end.year}.zip"
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/submission/readiness")
def submission_readiness():
    from submission import readiness
    from arelle_validator import capabilities
    return {**readiness(), "validator": capabilities()}


@app.post("/api/snapshot/{filing_id}/independent-validation")
def independent_validation(filing_id: str):
    """Diagnostic only; does not freeze, validate or authorize a submission."""
    from arelle_validator import diagnose
    from generator import generate_ixbrl
    try:
        snap = store.get(filing_id)
        taxonomy = taxonomy_registry.get(snap.taxonomy_id)
        document = store.get_document(snap.document_sha256)
        if document is None:
            raise ValueError("Source document is required.")
        ep = taxonomy.entry_points[snap.entry_point_key]
        # Map a local entrypoint to its package path for offline preparation.
        if not ep.startswith(("http://", "https://")) and getattr(taxonomy, "package_path", ""):
            ep = (Path(taxonomy.package_path) / ep).resolve().as_uri()
        payload = generate_ixbrl(snap, taxonomy.namespaces, entry_point=ep, document=document)
        package = getattr(taxonomy, "package_path", "")
        catalog_metadata = Path(package) / "META-INF" / "taxonomyPackage.xml" if package else None
        packages = [catalog_metadata] if catalog_metadata and catalog_metadata.is_file() else []
        return diagnose(payload.encode(), packages=packages)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/snapshot/{filing_id}/provider-handoff")
def provider_handoff(filing_id: str):
    from submission import create_handoff
    try:
        snap = store.get(filing_id)
        payload = filing_service.validate_and_package(snap, store.get_document(snap.document_sha256))
        bundle = create_handoff(payload, snap, taxonomy_registry.get(snap.taxonomy_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ExportBlocked, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StreamingResponse(io.BytesIO(bundle), media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="provider-handoff.zip"'})


# ── KVK entity lookup ──────────────────────────────────────────────────────────

@app.get("/api/kvk-lookup/{kvk_number}", response_model=KvkLookupOut)
async def lookup_kvk(kvk_number: str) -> KvkLookupOut:
    """Look up a KVK entity.  Uses the real KVK API if KVK_API_KEY is set."""
    if len(kvk_number) != 8 or not kvk_number.isascii() or not kvk_number.isdigit():
        raise HTTPException(status_code=422, detail="KVK number must be eight ASCII digits.")
    api_key = os.environ.get("KVK_API_KEY")

    if api_key:
        import httpx
        url = f"https://api.kvk.nl/api/v2/zoeken?kvknummer={kvk_number}"
        headers = {"apikey": api_key}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                results = data.get("resultaten", [])
                if results:
                    return KvkLookupOut(
                        found=True, kvk_number=kvk_number,
                        entity_name=results[0].get("naam"), source="kvk-api",
                    )
            elif response.status_code == 404:
                return KvkLookupOut(found=False, error="Not found in KVK registry")
            return KvkLookupOut(found=False, error=f"API Error {response.status_code}")
        except Exception as exc:
            return KvkLookupOut(found=False, error=f"Connection error: {exc}")
    else:
        return KvkLookupOut(found=False, source="unconfigured", error="KVK lookup is not configured. Enter entity details manually.")


# ── Workspace save / load ──────────────────────────────────────────────────────

@app.post("/api/workspace/save", response_model=WorkspaceOut)
async def save_workspace(payload: WorkspaceSaveIn) -> WorkspaceOut:
    try:
        path = store.save_to_disk(payload.kvk_number, payload.filing_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return WorkspaceOut(
        kvk_number=payload.kvk_number,
        filing_id=payload.filing_id,
        saved_at=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/api/workspace/load/{kvk_number}", response_model=SnapshotOut)
async def load_workspace(kvk_number: str, filing_id: str | None = None) -> SnapshotOut:
    try:
        snap = store.load_from_disk(kvk_number, filing_id)
        return _snap_out(snap)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No saved workspace for KVK {kvk_number}.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Static frontend ────────────────────────────────────────────────────────────

_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "frontend"))
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
