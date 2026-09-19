from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")

# Check the actual definition linkbase for concepts
def_xsd = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/validation/kvk-balance-sheet_u-def.xml"
print(f"Exists: {def_xsd.exists()}")
tree = ET.parse(str(def_xsd))
root = tree.getroot()

# Find all schema imports or references to the actual XSD files
print("Root tag:", root.tag)
for child in list(root)[:5]:
    print("  Child:", child.tag, dict(child.attrib))

# Find all locs (locators point to concept definitions)
locs = root.findall(".//{http://www.xbrl.org/2003/linkbase}loc")
print(f"\nLocs: {len(locs)}")
for loc in locs[:10]:
    href = loc.get("{http://www.w3.org/1999/xlink}href", "")
    print(f"  {href}")
