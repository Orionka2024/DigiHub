"""Execute the official iXBRL suite's declared expectations, not NT fixtures.

Usage: python conformance.py --suite path.zip --packages dir --output result.json
Use --limit 2 for an infrastructure smoke test; partial runs cannot qualify.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import zipfile
from lxml import etree

from arelle_validator import diagnose, capabilities
from reporting_profile import RULES_2025


def cases(archive):
    result = []
    ns = {"t": "http://xbrl.org/2008/conformance"}
    for name in archive.namelist():
        if "/tests/" not in name or not name.endswith("/index.xml"):
            continue
        root = etree.fromstring(archive.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
        automatable = root.findtext("t:automatable", namespaces=ns) == "true"
        for variation in root.findall("t:variation", ns):
            inputs = variation.findall('t:data/*[@readMeFirst="true"]', ns)
            expected = variation.find("t:result", ns)
            errors = [] if expected is None else [e.text for e in expected.findall('t:error', ns)]
            path = str(PurePosixPath(name).parent / inputs[0].text) if len(inputs) == 1 else None
            result.append({"id": str(PurePosixPath(name).parent.name) + "/" + variation.get("id"),
                           "path": path, "automatable": automatable,
                           "expected_valid": expected is not None and expected.get("expected") == "valid",
                           "expected_errors": errors})
    if not result:
        raise ValueError("No official iXBRL cases found; NT XBRL suites are not interchangeable.")
    return result


def run(suite, packages, limit=None):
    evidence = {"suite_sha256": sha256(suite.read_bytes()).hexdigest(),
                "rules_version": RULES_2025, "engine": capabilities(),
                "profile": "NL-INLINE-2025", "qualified": False,
                "package_checksums": {p.name: sha256(p.read_bytes()).hexdigest() for p in packages}, "results": []}
    with zipfile.ZipFile(suite) as archive:
        inventory = cases(archive)
        evidence["total_cases"] = len(inventory)
        for case in inventory[:limit]:
            if not case["automatable"] or not case["path"] or not (case["expected_valid"] or case["expected_errors"]):
                evidence["results"].append({**case, "status": "manual_review_required"})
                continue
            result = diagnose(archive.read(case["path"]), suffix=".xbri", packages=packages, profile="NL-INLINE-2025")
            codes = {str(m.get("code", "")) for m in result["messages"]}
            # Match the actual expected error, never treat any generic failure as
            # a successful negative test. Missing DTS dependencies cannot pass.
            expected_hit = all(any(c == e or c.endswith(':' + e) or c.endswith('.' + e) for c in codes)
                               for e in case["expected_errors"])
            infrastructure_failure = (result.get("engine_failure", False) or not result.get("completed", False) or
                any(any(x in c.lower() for x in ("ioerror", "filenotloadable", "validation_incomplete", "validator_", "engine_missing", "pluginloadingerror", "disclosuresystemname")) for c in codes))
            passed = (result["technical_valid"] if case["expected_valid"] else expected_hit and not result["technical_valid"])
            evidence["results"].append({**case, "status": "pass" if passed and not infrastructure_failure else "fail", "diagnostics": result})
    evidence["executed_cases"] = len(evidence["results"])
    evidence["all_automated_cases_passed"] = (len(evidence["results"]) == evidence["total_cases"]
        and all(r["status"] == "pass" for r in evidence["results"]))
    # Passing this suite is evidence, not application accounting certification.
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    report = run(args.suite, sorted([*args.packages.glob('*taxonomie.zip'), *args.packages.glob('lei-*.zip'), *args.packages.glob('xbrl-*-support.zip')]), args.limit)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ('total_cases', 'executed_cases', 'all_automated_cases_passed', 'qualified')}))
