from KVK_v2.app.main import taxonomy_registry
release = taxonomy_registry.get("NT21_KVK_20261209_b")
print("Class:", release.__class__.__name__)
if hasattr(release, "rules_engine"):
    print("Has rules engine!")
else:
    print("No rules engine!")
