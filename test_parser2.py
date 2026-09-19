from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")
ep_xsd = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/entrypoints/kvk-rpt-jaarverantwoording-2026-nlgaap-micro.xsd"

print("Exists:", ep_xsd.exists())
tree = ET.parse(str(ep_xsd))
root = tree.getroot()

# Check all imports
imports = root.findall("{http://www.w3.org/2001/XMLSchema}import")
print(f"Imports: {len(imports)}")
for imp in imports[:5]:
    print(f"  schemaLocation: {imp.get('schemaLocation')}")
    print(f"  namespace: {imp.get('namespace')}")

# Check all elements
elements = root.findall("{http://www.w3.org/2001/XMLSchema}element")
print(f"Elements in entry-point XSD: {len(elements)}")
for el in elements[:5]:
    print(f"  name={el.get('name')}, type={el.get('type')}, subgroup={el.get('substitutionGroup')}")

# Check linkbaseRefs
linkbaseRefs = root.findall("{http://www.xbrl.org/2003/linkbase}linkbaseRef", 
    namespaces={"xbrli": "http://www.xbrl.org/2003/instance"})
print(f"LinkbaseRefs: {len(linkbaseRefs)}")

# Find any linkbaseRef in annotation/appinfo
for ann in root.iter("{http://www.w3.org/2001/XMLSchema}annotation"):
    for app in ann.iter("{http://www.w3.org/2001/XMLSchema}appinfo"):
        for lb in app.iter():
            if "linkbaseRef" in lb.tag:
                print(f"  linkbaseRef: {lb.get('{http://www.w3.org/1999/xlink}href', '')}")
