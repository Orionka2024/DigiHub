import sys
from KVK_v2.app.main import taxonomy_registry, filing_service, _load_verified_taxonomies, _parse_release_ep
from KVK_v2.registry import TaxonomyRegistry

rel = taxonomy_registry.get_enriched("NT21_KVK_20261209_b")
# ensure it's loaded
_parse_release_ep(rel, "groot_nlgaap")

try:
    sections = rel.build_checklist("groot_nlgaap", snapshot=None)
    print(f"Success! {len(sections)} sections")
except Exception as e:
    import traceback
    traceback.print_exc()
