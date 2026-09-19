import re

with open("app/main.py", "r") as f:
    content = f.read()

old_autotag = """@app.post("/api/snapshot/{filing_id}/auto-tag-table", response_model=AutoTagResponse)
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
        
    requirements = taxonomy.requirements.get(snap.entry_point_key, [])
    recommendations = recommend_tags(node, requirements)
    
    return AutoTagResponse(recommendations=recommendations)"""

new_autotag = """@app.post("/api/snapshot/{filing_id}/auto-tag-table", response_model=AutoTagResponse)
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
        concepts = taxonomy.get_concepts(snap.entry_point_key)
        # We only care about monetary/numeric concepts
        requirements = [c for c in concepts if c.is_numeric()]
    else:
        requirements = taxonomy.requirements.get(snap.entry_point_key, [])
        
    recommendations = recommend_tags(node, requirements)
    
    return AutoTagResponse(recommendations=recommendations)"""

content = content.replace(old_autotag, new_autotag)

with open("app/main.py", "w") as f:
    f.write(content)
