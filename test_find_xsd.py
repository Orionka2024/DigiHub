from pathlib import Path

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")
ep_xsd = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/entrypoints/kvk-rpt-jaarverantwoording-2026-nlgaap-micro.xsd"

import xml.etree.ElementTree as ET
tree = ET.parse(str(ep_xsd))
root = tree.getroot()

# Check what schemas the entry point imports (the single xbrl-linkbase)
for imp in root.iter("{http://www.w3.org/2001/XMLSchema}import"):
    print("Schema import:", imp.get("schemaLocation"))
    print("  namespace:", imp.get("namespace"))

# Check if there is an xs:include or other mechanism 
for inc in root.iter("{http://www.w3.org/2001/XMLSchema}include"):
    print("Schema include:", inc.get("schemaLocation"))

# Check if there are any elements defined directly
print()
print("Direct elements in EP XSD:")
for el in root.iter("{http://www.w3.org/2001/XMLSchema}element"):
    print(f"  {el.get('name')}")

# The actual concept XSDs must be referenced via linkbaseRefs that point to XSDs!
# Let's look at a def.xml and see if it has xs:import
def_path = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/dictionary"
print()
print("Dictionary files:")
for f in def_path.glob("*.xsd"):
    print(f"  {f.name}")
