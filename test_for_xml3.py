from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")

for_file = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/validation/kvk-balance-sheet_u-for.xml"
tree = ET.parse(str(for_file))
root = tree.getroot()

# Find all variable elements and their concept filters
variables = root.findall(".//{http://xbrl.org/2008/variable}factVariable")
print(f"factVariables: {len(variables)}")
for v in variables[:10]:
    vid = v.get("{http://www.w3.org/1999/xlink}label","")
    print(f"  factVariable: {vid}")

# Find conceptName filters  
concepts = root.findall(".//{http://xbrl.org/2008/filter/concept}conceptName")
print(f"\nconceptName filters: {len(concepts)}")
for cf in concepts[:10]:
    for q in cf:
        tag = q.tag.split("}")[-1] if "}" in q.tag else q.tag
        print(f"  {tag}: {q.text}")

# Find variableArc connections
var_arcs = root.findall(".//{http://xbrl.org/2008/variable}variableArc")
print(f"\nvariableArcs: {len(var_arcs)}")
for arc in var_arcs[:10]:
    frm = arc.get("{http://www.w3.org/1999/xlink}from","")
    to = arc.get("{http://www.w3.org/1999/xlink}to","")
    name = arc.get("name","")
    arcrole = arc.get("{http://www.w3.org/1999/xlink}arcrole","").split("/")[-1]
    print(f"  {frm} -> {to} (name={name}, arcrole={arcrole})")
