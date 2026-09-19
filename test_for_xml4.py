from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")

for_file = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/validation/kvk-balance-sheet_u-for.xml"
tree = ET.parse(str(for_file))
root = tree.getroot()

# Check the schemaLocation for concept namespaces
schema_location = root.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", "")
print("schemaLocation:", schema_location[:500])

# Find concept qname elements in concept filters
for cf in root.iter("{http://xbrl.org/2008/filter/concept}conceptName"):
    print(f"\nconceptName element:")
    for child in cf:
        print(f"  tag: {child.tag}")
        print(f"  text: '{child.text}'")
        print(f"  attrib: {dict(child.attrib)}")
    break

# Check the schemaLocation attribute on the linkbase root — it lists concept namespaces
for ns_uri, ns_pair in [("http://www.nltaxonomie.nl/nt21/jenv/20261209.b/dictionary/jenv-bw2-data", 
                          "jenv-bw2-data")]:
    # Find XSD for this namespace via catalog
    from KVK_v2.taxonomy_parser import CatalogResolver
    catalog_path = pkg / "META-INF" / "catalog.xml"
    resolver = CatalogResolver(catalog_path)
    result = resolver.resolve(ns_uri + ".xsd")
    print(f"\nResolve {ns_uri}.xsd => {result}")
    if result and result.exists():
        t3 = ET.parse(str(result))
        r3 = t3.getroot()
        els = r3.findall("{http://www.w3.org/2001/XMLSchema}element")
        print(f"  Elements: {len(els)}")
        for el in els[:5]:
            print(f"    {el.get('name')}: type={el.get('type')}, subgroup={el.get('substitutionGroup')}")
