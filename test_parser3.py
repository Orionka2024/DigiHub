from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")
ep_xsd = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/entrypoints/kvk-rpt-jaarverantwoording-2026-nlgaap-micro.xsd"

# Check what imports reference
tree = ET.parse(str(ep_xsd))
root = tree.getroot()

imports = root.findall("{http://www.w3.org/2001/XMLSchema}import")
print(f"Imports: {len(imports)}")
for imp in imports[:10]:
    schema_loc = imp.get("schemaLocation", "")
    print(f"  import: {schema_loc}")

# Look at one of the imported schemas
print()
# Check what one referenced schema looks like
if imports:
    schema_loc = imports[0].get("schemaLocation", "")
    if schema_loc:
        ref_path = (ep_xsd.parent / schema_loc).resolve()
        print(f"Checking imported schema: {ref_path}")
        if ref_path.exists():
            t2 = ET.parse(str(ref_path))
            r2 = t2.getroot()
            elements = r2.findall("{http://www.w3.org/2001/XMLSchema}element")
            print(f"  Elements in imported schema: {len(elements)}")
            for el in elements[:5]:
                print(f"    name={el.get('name')}, subgroup={el.get('substitutionGroup')}")
