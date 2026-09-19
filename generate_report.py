from KVK_v2.app.main import taxonomy_registry
import json

release = taxonomy_registry.get("NT21_KVK_20261209_b")

ep = "groot_nlgaap"
concepts = release.get_concepts_for_ep(ep)
from KVK_v2.taxonomy.rules import MandatoryStatus

mandatory = sum(1 for c in concepts if release.rules_engine.get_concept_status(c.qname, ep) == MandatoryStatus.MANDATORY)
conditional = sum(1 for c in concepts if release.rules_engine.get_concept_status(c.qname, ep) == MandatoryStatus.CONDITIONAL)
optional = sum(1 for c in concepts if release.rules_engine.get_concept_status(c.qname, ep) == MandatoryStatus.OPTIONAL)

print("C. Taxonomy package installed: NT21_KVK")
print(f"D. Exact taxonomy version: {release.id}")
print(f"E. Exact KVK entry point(s): {list(release.entry_points.keys())[:5]} ...")
print(f"F. Number of concepts imported: {len(release.concepts)}")
print(f"G. Number of rules imported: {len(release.rules_engine.get_all_rules())}")
print(f"H. Number of relationships imported: (many calc/pres relationships stored inside concepts)")
print(f"I. Number of mandatory concepts detected (groot_nlgaap): {mandatory}")
print(f"J. Number of conditional concepts detected (groot_nlgaap): {conditional}")
print(f"K. Number of optional concepts detected (groot_nlgaap): {optional}")
