import json
from pathlib import Path
with open("app/data/taxonomies/nt21_kvk.json", "r") as f:
    manifest = json.load(f)
package_filename = manifest.get("package_filename", f"{manifest['id']}.zip")
_TAXONOMY_DIR = Path("app/data/taxonomies")
package_path = _TAXONOMY_DIR / package_filename
print(package_path, "is_dir?", package_path.is_dir())
