import re
with open("taxonomy/importer.py", "r") as f:
    content = f.read()
content = content.replace("ConceptMeta", "ConceptMetadata")
with open("taxonomy/importer.py", "w") as f:
    f.write(content)
