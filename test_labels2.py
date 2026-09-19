from pathlib import Path
from KVK_v2.taxonomy_parser import TaxonomyParser

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")
catalog = pkg / "META-INF" / "catalog.xml"
parser = TaxonomyParser(pkg, catalog)

ep_file = "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/entrypoints/kvk-rpt-jaarverantwoording-2026-nlgaap-micro.xsd"
c_dict, r_list = parser.parse_entry_point(ep_file, "micro_nlgaap")

# The _labels keys use a prefix format, not local_name only
# Check the first label key and match it against concepts
for key in list(parser._labels.keys())[:3]:
    roles = parser._labels[key]
    for role, langs in roles.items():
        label_nl = langs.get("nl", "")
        if label_nl:
            print(f"Key: {key!r} => NL label: {label_nl[:60]}")
            break

# Check what the _loc_map looks like
print("\nSample _loc_map entries (first 5):")
for key, val in list(parser._loc_map.items())[:10]:
    print(f"  {key!r} => {val!r}")
    
print(f"\nTotal _loc_map size: {len(parser._loc_map)}")
print(f"Total _labels size: {len(parser._labels)}")
print(f"Total concepts: {len(parser.concepts)}")

# Check if any label key matches a local_name
concept_local_names = {c.local_name for c in parser.concepts.values()}
matching_labels = {k for k in parser._labels.keys() if k in concept_local_names}
print(f"\nLabel keys that match a concept local_name: {len(matching_labels)}")
if matching_labels:
    for k in list(matching_labels)[:3]:
        print(f"  {k}: {parser._labels[k]}")
