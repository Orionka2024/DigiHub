from KVK_v2.app.main import taxonomy_registry
from KVK_v2.taxonomy.rules import MandatoryStatus

release = taxonomy_registry.get("NT21_KVK_20261209_b")
print("Class:", release.__class__.__name__)
print("Version:", release.version)
print("Name:", release.name)
print("Authority:", release.authority)
print("Reporting date:", release.reporting_date)
print("Total concepts:", len(release.concepts))
print("Total rules:", len(release.rules_engine.get_all_rules()))
print("Total entry points:", len(release.entry_points))

# Check one EP
for ep_key in list(release.entry_points.keys())[:5]:
    concepts = release.get_concepts_for_ep(ep_key)
    mandatory = sum(1 for c in concepts if release.rules_engine.get_concept_status(c.qname, ep_key) == MandatoryStatus.MANDATORY)
    conditional = sum(1 for c in concepts if release.rules_engine.get_concept_status(c.qname, ep_key) == MandatoryStatus.CONDITIONAL)
    optional = sum(1 for c in concepts if release.rules_engine.get_concept_status(c.qname, ep_key) == MandatoryStatus.OPTIONAL)
    print(f"\nEntry point '{ep_key}':")
    print(f"  Concepts: {len(concepts)}")
    print(f"  Mandatory: {mandatory}")
    print(f"  Conditional: {conditional}")
    print(f"  Optional: {optional}")
    if concepts:
        sample = concepts[:3]
        for c in sample:
            print(f"  Sample: {c.qname} | {c.label_nl[:40] if c.label_nl else '(no label)'}")
