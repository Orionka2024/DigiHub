from dataclasses import dataclass
@dataclass
class ValidationRule:
    concept_qname: str

requirements = [ValidationRule("test:Concept")]
try:
    req_qnames = [r.qname for r in requirements if r.qname]
    print("SUCCESS:", req_qnames)
except Exception as e:
    print("ERROR:", type(e), e)
