from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")

# Find actual concept XSD files 
for_file = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/validation/kvk-balance-sheet_u-for.xml"
tree = ET.parse(str(for_file))
root = tree.getroot()

# Print the structure to understand
def print_tree(el, depth=0):
    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    attrs = {k.split("}")[-1]: v for k, v in el.attrib.items()}
    print("  " * depth + f"<{tag} {attrs}>")
    if el.text and el.text.strip():
        print("  " * (depth+1) + el.text.strip())
    for child in list(el)[:3]:
        print_tree(child, depth+1)
    if len(el) > 3:
        print("  " * (depth+1) + f"... ({len(el)-3} more children)")

print_tree(root)
