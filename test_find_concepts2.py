from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")

# Check the balance-sheet presentation file 
for tab in pkg.glob("**/*balance-sheet*tab*.xml"):
    print(f"File: {tab.name}")
    tree = ET.parse(str(tab))
    root = tree.getroot()
    locs = root.findall(".//{http://www.xbrl.org/2003/linkbase}loc")
    if locs:
        for loc in locs[:5]:
            href = loc.get("{http://www.w3.org/1999/xlink}href", "")
            print(f"  {href}")
    break
