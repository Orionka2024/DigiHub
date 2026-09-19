from pathlib import Path
from KVK_v2.taxonomy_parser import TaxonomyParser

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")
catalog = pkg / "META-INF" / "catalog.xml"
parser = TaxonomyParser(pkg, catalog)

ep_file = "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/entrypoints/kvk-rpt-jaarverantwoording-2026-nlgaap-micro.xsd"
c_dict, r_list = parser.parse_entry_point(ep_file, "micro_nlgaap")
print(f"Concepts: {len(c_dict)}")
print(f"Labels accumulated: {len(parser._labels)}")

# Show first 5 concepts with labels
labeled = [(qn, c) for qn, c in c_dict.items() if c.label_nl]
print(f"Concepts with NL labels: {len(labeled)}")
if labeled:
    for qn, c in labeled[:5]:
        print(f"  {qn} | {c.label_nl[:60]}")
else:
    print("  (none)")
    # Check what's in _labels
    print(f"  _labels keys (first 5): {list(parser._labels.keys())[:5]}")
    # Check the first concept's local_name
    first = next(iter(c_dict.values()))
    print(f"  First concept local_name: '{first.local_name}'")
    # Is there a label for it?
    print(f"  Label for '{first.local_name}': {parser._labels.get(first.local_name, {})}")
