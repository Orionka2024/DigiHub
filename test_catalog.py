from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")
catalog_path = pkg / "META-INF" / "catalog.xml"
print("Catalog exists:", catalog_path.exists())

tree = ET.parse(str(catalog_path))
root = tree.getroot()
print("Catalog root:", root.tag)

# Check rewrite rules
for child in root:
    print(f"  {child.tag}: {dict(child.attrib)}")
