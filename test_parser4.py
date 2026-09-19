from pathlib import Path
from taxonomy_parser import TaxonomyParser

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")
catalog = pkg / "META-INF" / "catalog.xml"
parser = TaxonomyParser(pkg, catalog)

# Manually trace: what files does the entry point XSD reference?
ep_xsd = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/entrypoints/kvk-rpt-jaarverantwoording-2026-nlgaap-micro.xsd"

import xml.etree.ElementTree as ET
tree = ET.parse(str(ep_xsd))
root = tree.getroot()

# Check linkbaseRef in appinfo
print("=== linkbaseRefs in entry point ===")
for lb in root.iter("{http://www.xbrl.org/2003/linkbase}linkbaseRef"):
    href = lb.get("{http://www.w3.org/1999/xlink}href", "")
    resolved = parser._resolve(href, ep_xsd)
    print(f"  {href}")
    print(f"    => {resolved}, exists={resolved.exists() if resolved else 'N/A'}")
    # If it references a schema file, check it for elements
    if resolved and resolved.suffix == ".xsd" and resolved.exists():
        t2 = ET.parse(str(resolved))
        r2 = t2.getroot()
        els = r2.findall("{http://www.w3.org/2001/XMLSchema}element")
        print(f"    elements: {len(els)}")
