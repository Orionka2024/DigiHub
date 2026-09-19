from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")

# The locs in linkbases reference the actual XSD files
# Let's look at the presentation linkbase to understand concept references
pres_file = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/presentation/kvk-balance-sheet_u-tab.xml"
print(f"Pres file exists: {pres_file.exists()}")
tree = ET.parse(str(pres_file))
root = tree.getroot()

locs = root.findall(".//{http://www.xbrl.org/2003/linkbase}loc")
print(f"Locs: {len(locs)}")
for loc in locs[:15]:
    href = loc.get("{http://www.w3.org/1999/xlink}href", "")
    lbl = loc.get("{http://www.w3.org/1999/xlink}label", "")
    print(f"  [{lbl}] {href}")
