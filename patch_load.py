import re

with open("app/main.py", "r") as f:
    content = f.read()

old_code = """            # If requirements are not in manifest, parse them dynamically!
            req_dict = {}
            if "requirements" not in manifest and package_path.is_dir():
                from KVK_v2.taxonomy_parser import TaxonomyParser
                catalog_path = package_path / "META-INF" / "catalog.xml"
                parser = TaxonomyParser(package_path, catalog_path if catalog_path.exists() else None)
                
                for ep_key, ep_file in manifest["entry_points"].items():
                    reqs = parser.parse_entry_point(ep_file)
                    req_dict[ep_key] = tuple(reqs)
            else:
                # If they are in the JSON manifest, we just assume they apply to all entry points for backward compatibility
                req_tuple = tuple(TaggingRequirement(**item) for item in manifest.get("requirements", []))
                for ep_key in manifest["entry_points"].keys():
                    req_dict[ep_key] = req_tuple

            release = TaxonomyRelease(
                id=manifest["id"], status=manifest["status"],
                entry_points=manifest["entry_points"], namespaces=manifest["namespaces"],
                sha256=digest, package_verified=package_verified,
                requirements=req_dict,
            )"""

new_code = """            # If requirements are not in manifest, parse them dynamically!
            if "requirements" not in manifest and package_path.is_dir():
                from KVK_v2.taxonomy_parser import TaxonomyParser
                from KVK_v2.taxonomy.rules import RulesEngine
                from KVK_v2.registry import EnrichedTaxonomyRelease
                
                catalog_path = package_path / "META-INF" / "catalog.xml"
                parser = TaxonomyParser(package_path, catalog_path if catalog_path.exists() else None)
                
                concepts_all = {}
                rules_engine = RulesEngine()
                
                for ep_key, ep_file in manifest["entry_points"].items():
                    c_dict, r_list = parser.parse_entry_point(ep_file, ep_key)
                    concepts_all.update(c_dict)
                    for rule in r_list:
                        rules_engine.add_rule(rule)
                        
                release = EnrichedTaxonomyRelease(
                    id=manifest["id"], status=manifest["status"],
                    entry_points=manifest["entry_points"], namespaces=manifest["namespaces"],
                    sha256=digest, package_verified=package_verified,
                    concepts=concepts_all, rules_engine=rules_engine
                )
            else:
                req_dict = {}
                # If they are in the JSON manifest, we just assume they apply to all entry points for backward compatibility
                req_tuple = tuple(TaggingRequirement(**item) for item in manifest.get("requirements", []))
                for ep_key in manifest["entry_points"].keys():
                    req_dict[ep_key] = req_tuple

                release = TaxonomyRelease(
                    id=manifest["id"], status=manifest["status"],
                    entry_points=manifest["entry_points"], namespaces=manifest["namespaces"],
                    sha256=digest, package_verified=package_verified,
                    requirements=req_dict,
                )"""

content = content.replace(old_code, new_code)
with open("app/main.py", "w") as f:
    f.write(content)
