from KVK_v2.app.store import store
from KVK_v2.registry import taxonomy_registry
from KVK_v2.autotagger import recommend_tags, _camel_to_words, _clean_text

snap = store.load_from_disk("34254022")
doc = store.get_document(snap.document_sha256)
tax = taxonomy_registry.get(snap.taxonomy_id)
reqs = tax.requirements.get(snap.entry_point_key, [])

print(f"Total reqs: {len(reqs)}")
print("Sample reqs:", [r.qname for r in reqs[:5]])

for node in doc.nodes:
    if node.kind == "table":
        print("TABLE:", node.id)
        for row in node.rows:
            if row:
                print("  ROW:", row[0], "--> clean:", _clean_text(row[0]))

print("CAMEL:", _camel_to_words("CashAndCashEquivalents"))

