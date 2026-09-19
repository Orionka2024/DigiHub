from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")

# Find actual concept XSD files — they're in the SBR/JENV namespace directories
# The key are the import namespaces referenced from the for.xml or def.xml files
for_file = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/validation/kvk-balance-sheet_u-for.xml"
tree = ET.parse(str(for_file))
root = tree.getroot()

# cf:conceptName elements contain actual concept qnames!
for cf in root.iter("{http://xbrl.org/2008/filter/concept}conceptName"):
    for q in cf:
        if "qname" in q.tag:
            print(f"Concept referenced in for.xml: {q.text}")
