from app.main import taxonomy_registry
from taxonomy.rules import MandatoryStatus

rel = taxonomy_registry.get("NT21_KVK_20261209_b")

# Check rules
rules = rel.rules_engine.get_all_rules()
print(f"Total rules: {len(rules)}")
for r in rules[:5]:
    print(f"  {r.rule_id}: status={r.status}, concept={r.concept_qname}, entry_points={r.entry_points}")

# Check get_concept_status for mandatory concepts
print("\nCheck concept status for existence assertion targets:")
for r in rules:
    if r.status == MandatoryStatus.MANDATORY and r.concept_qname:
        status = rel.rules_engine.get_concept_status(r.concept_qname, "micro_nlgaap")
        print(f"  {r.concept_qname}: status={status}")
        break

# Direct check
print("\nDirect _rules_by_concept_ep keys (first 5):")
for key in list(rel.rules_engine._rules_by_concept_ep.keys())[:5]:
    print(f"  {key}")
    
print("\nDirect _rules_by_ep keys:")
for key in list(rel.rules_engine._rules_by_ep.keys()):
    print(f"  {key}: {len(rel.rules_engine._rules_by_ep[key])} rules")
