"""Isolated, offline Arelle diagnostics. Technical success is not filing approval."""
from __future__ import annotations

from hashlib import sha256
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def capabilities():
    try:
        import arelle
        from lxml import etree
        config = Path(arelle.__file__).parent / "plugin/validate/NL/resources/config.xml"
        root = etree.parse(str(config), etree.XMLParser(resolve_entities=False, no_network=True))
        profiles = [node.get("names").split("|")[0] for node in root.findall("DisclosureSystem")]
        return {"installed": True, "version": version("arelle-release"), "profiles": profiles,
                "filing_approval": False}
    except (ImportError, PackageNotFoundError, OSError):
        return {"installed": False, "version": None, "profiles": [], "filing_approval": False}


def diagnose(payload: bytes, *, suffix=".xhtml", packages=(), profile=None, timeout=120):
    """Run against local packages only, without persistent user configuration.

    No disclosure profile is guessed from a reporting year. All diagnostics,
    including warnings, are returned; this function never authorizes export.
    """
    info = capabilities()
    result = {"engine": info, "sha256": sha256(payload).hexdigest(), "profile": profile,
              "technical_valid": False, "suitable_for_filing": False, "messages": []}
    if not info["installed"]:
        result["messages"] = [{"code": "ENGINE_MISSING", "message": "Install app/requirements-validator.txt."}]
        return result
    if profile and profile not in info["profiles"]:
        result["messages"] = [{"code": "PROFILE_UNAVAILABLE", "message": f"Unsupported profile: {profile}"}]
        return result
    if suffix not in (".xhtml", ".zip", ".xbri", ".xbrl"):
        raise ValueError("Unsupported diagnostic document type.")
    if suffix == ".xhtml":
        from lxml import etree
        try:
            doc = etree.fromstring(payload, etree.XMLParser(resolve_entities=False, no_network=True))
            ns = {"ix": "http://www.xbrl.org/2013/inlineXBRL", "link": "http://www.xbrl.org/2003/linkbase"}
            if not doc.xpath("//ix:references/link:schemaRef", namespaces=ns):
                result["messages"] = [{"code": "IXBRL_REQUIRED", "message": "An inline report with a taxonomy reference is required."}]
                return result
        except etree.XMLSyntaxError:
            pass  # Arelle returns the detailed parse failure.
    paths = [Path(p).resolve(strict=True) for p in packages]
    if any("|" in str(p) for p in paths):
        raise ValueError("Package paths cannot contain |.")
    with TemporaryDirectory(prefix="kvk-arelle-") as folder:
        root = Path(folder)
        report = root / ("report" + suffix)
        report.write_bytes(payload)
        log = root / "validation.json"
        command = [sys.executable, "-m", "arelle.CntlrCmdLine", "--file", str(report),
                   "--validate", "--validationExitCode", "--formula", "run",
                   "--formulaUnsatisfiedAsserError", "--calc", "c10",
                   "--internetConnectivity", "offline", "--xdgConfigHome", str(root / "config"),
                   "--logFile", str(log), "--logLevel", "INFO"]
        if paths:
            command += ["--packages", "|".join(map(str, paths))]
        if profile:
            command += ["--plugins", "validate/NL", "--disclosureSystem", profile]
        try:
            run = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
            messages = json.loads(log.read_text())["log"]
            result["messages"] = messages
            completed = any("validated in" in m.get("message", {}).get("text", "") for m in messages)
            errors = any(m.get("level", "").lower() in ("error", "critical", "fatal") for m in messages)
            result["technical_valid"] = run.returncode == 0 and completed and not errors
            if not completed:
                messages.append({"code": "VALIDATION_INCOMPLETE", "message": "No completed validation was recorded."})
        except subprocess.TimeoutExpired:
            result["messages"] = [{"code": "VALIDATOR_TIMEOUT", "message": "Validation exceeded its time limit."}]
        except (OSError, ValueError, KeyError, TypeError):
            result["messages"] = [{"code": "VALIDATOR_FAILURE", "message": "Validator did not produce a readable result."}]
    return result


def validate_report(ixbrl, snapshot, taxonomy):
    """Fail-closed adapter for KVK_VALIDATOR; 2026 filing coverage is not qualified."""
    report = diagnose(ixbrl.encode())
    issues = ["VALIDATION_INCOMPLETE: Arelle integration is diagnostic only; the applicable filing profile and report package must be qualified."]
    if not report["technical_valid"]:
        issues.append("ARELLE: Technical validation failed. Run independent-validation for details.")
    return issues


validate_report.filing_approval = False
