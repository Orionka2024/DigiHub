from pathlib import Path
from taxonomy_parser import TaxonomyParser
from taxonomy.rules import MandatoryStatus

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")
catalog = pkg / "META-INF" / "catalog.xml"
parser = TaxonomyParser(pkg, catalog)

ep_file = "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/entrypoints/kvk-rpt-jaarverantwoording-2026-nlgaap-micro.xsd"
c_dict, r_list = parser.parse_entry_point(ep_file, "micro_nlgaap")
print(f"Concepts: {len(c_dict)}")
print(f"Rules: {len(r_list)}")
if c_dict:
    first = next(iter(c_dict.values()))
    print(f"Sample concept: {first.qname} | label_nl='{first.label_nl}' | status={first.mandatory_status}")
if r_list:
    print(f"Sample rule: {r_list[0].rule_id} | status={r_list[0].status}")
