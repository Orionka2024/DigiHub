import re

with open("app/main.py", "r") as f:
    content = f.read()

# Define the new endpoints
new_endpoints = """# ── Taxonomy endpoints ─────────────────────────────────────────────────────────

from KVK_v2.registry import EnrichedTaxonomyRelease
from KVK_v2.app.models_api import (
    EnrichedTaxonomyReleaseOut, ConceptMetadataOut, ValidationRuleOut,
    ChecklistSectionOut, SelectEntryPointOut
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
        return {"entry_points": rel.entry_points}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.get("/api/taxonomy/{taxonomy_id}/concepts")
async def get_concepts(taxonomy_id: str, entry_point_key: str = "") -> dict:
    try:
        rel = taxonomy_registry.get_enriched(taxonomy_id)
        if entry_point_key:
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
            from KVK_v2.app.store import store
            try:
                snap = store.get(filing_id)
            except KeyError:
                pass
        
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
"""

pattern = r"# ── Taxonomy endpoints ─────────────────────────────────────────────────────────\n.*?# ── Document extraction ────────────────────────────────────────────────────────"
new_content = re.sub(pattern, new_endpoints + "\n\n# ── Document extraction ────────────────────────────────────────────────────────", content, flags=re.DOTALL)

with open("app/main.py", "w") as f:
    f.write(new_content)

print("Updated app/main.py")
