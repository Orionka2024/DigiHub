from pathlib import Path
from KVK_v2.taxonomy_parser import CatalogResolver, TaxonomyParser

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")
catalog_path = pkg / "META-INF" / "catalog.xml"

resolver = CatalogResolver(catalog_path)
print("Resolver base_dir:", resolver.base_dir)
print("Resolver rules:", resolver.rules)

# Test resolving one concept schema
test_uri = "http://www.nltaxonomie.nl/nt21/kvk/20261209.b/validation/kvk-balance-sheet_u-for.xml"
result = resolver.resolve(test_uri)
print(f"\nResolve {test_uri}")
print(f"  => {result}")
print(f"  exists: {result.exists() if result else 'N/A'}")

# Test resolving the import URL 
import_uri = "http://www.xbrl.org/2003/xbrl-linkbase-2003-12-31.xsd"
result2 = resolver.resolve(import_uri)
print(f"\nResolve {import_uri}")
print(f"  => {result2}")
