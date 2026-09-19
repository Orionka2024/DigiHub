import json
with open("app/data/taxonomies/nt21_kvk.json", "r") as f:
    data = json.load(f)
data["package_filename"] = "nt21_kvk_20261209.b - taxonomyPackage"
with open("app/data/taxonomies/nt21_kvk.json", "w") as f:
    json.dump(data, f, indent=2)
