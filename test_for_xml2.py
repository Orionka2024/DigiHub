from pathlib import Path
import xml.etree.ElementTree as ET

pkg = Path("app/data/taxonomies/nt21_kvk_20261209.b - taxonomyPackage")

for_file = pkg / "taxonomie/www.nltaxonomie.nl/nt21/kvk/20261209.b/validation/kvk-balance-sheet_u-for.xml"
tree = ET.parse(str(for_file))
root = tree.getroot()

# Find gen:link elements
gen_links = root.findall("{http://xbrl.org/2008/generic}link")
print(f"gen:links: {len(gen_links)}")

for gl in gen_links[:3]:
    print(f"\n  gen:link role={gl.get('{http://www.w3.org/1999/xlink}role','')}")
    # Find existence assertions inside
    ea_list = gl.findall("{http://xbrl.org/2008/assertion/existence}existenceAssertion")
    print(f"  existenceAssertions: {len(ea_list)}")
    for ea in ea_list[:3]:
        print(f"    id={ea.get('id')}")
        # Find concept filter connected to this assertion
    
    # Find variable arcs
    var_arcs = gl.findall("{http://xbrl.org/2008/variable}variableArc")
    print(f"  variableArcs: {len(var_arcs)}")
    
    # Find variableFilterArc
    vf_arcs = gl.findall("{http://xbrl.org/2008/variable}variableFilterArc")
    print(f"  variableFilterArcs: {len(vf_arcs)}")
    for arc in vf_arcs[:3]:
        frm = arc.get("{http://www.w3.org/1999/xlink}from","")
        to = arc.get("{http://www.w3.org/1999/xlink}to","")
        print(f"    arc from={frm} to={to}")

# Find all gen:arcs
gen_arcs = root.findall(".//{http://xbrl.org/2008/generic}arc")
print(f"\nTotal gen:arcs: {len(gen_arcs)}")
for arc in gen_arcs[:5]:
    frm = arc.get("{http://www.w3.org/1999/xlink}from","")
    to = arc.get("{http://www.w3.org/1999/xlink}to","")
    role = arc.get("{http://www.w3.org/1999/xlink}arcrole","")
    print(f"  from={frm} to={to} arcrole={role.split('/')[-1]}")

# Find all locs
locs = root.findall(".//{http://www.xbrl.org/2003/linkbase}loc")
print(f"\nTotal locs: {len(locs)}")
for loc in locs[:5]:
    href = loc.get("{http://www.w3.org/1999/xlink}href","")
    lbl = loc.get("{http://www.w3.org/1999/xlink}label","")
    print(f"  [{lbl}] {href}")
