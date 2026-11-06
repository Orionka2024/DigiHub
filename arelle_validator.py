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
        # Reading config.xml alone does not prove the optional plug-in imports.
        import importlib
        try:
            importlib.import_module("arelle.plugin.validate.NL")
            plugin_error = None
        except ImportError as exc:
            profiles = []
            plugin_error = str(exc)
        return {"installed": True, "version": version("arelle-release"), "profiles": profiles,
                "filing_approval": False, "plugin_error": plugin_error}
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
    from reporting_profile import RULES_2025
    result["rules_version"] = RULES_2025 if profile == "NL-INLINE-2025" else None
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
    result["package_checksums"] = {str(p): sha256(p.read_bytes()).hexdigest() for p in paths}
    if any("|" in str(p) for p in paths):
        raise ValueError("Package paths cannot contain |.")
    with TemporaryDirectory(prefix="kvk-arelle-") as folder:
        root = Path(folder)
        report = root / ("report" + suffix)
        report.write_bytes(payload)
        log = root / "validation.json"
        command = [sys.executable, "-m", "arelle.CntlrCmdLine", "--file", str(report),
                   "--validate", "--validationExitCode",
                   "--formulaUnsatisfiedAsserError", "--calc", "c10",
                   "--internetConnectivity", "offline", "--xdgConfigHome", str(root / "config"),
                   "--logFile", str(log), "--logLevel", "INFO"]
        evidence_plugin = Path(__file__).with_name("validation_evidence_plugin.py")
        result["evidence_plugin_sha256"] = sha256(evidence_plugin.read_bytes()).hexdigest()
        plugins = [str(evidence_plugin)]
        if paths:
            command += ["--packages", "|".join(map(str, paths))]
        if profile:
            plugins.append("validate/NL")
            command += ["--disclosureSystem", profile]
        command += ["--plugins", "|".join(plugins)]
        try:
            run = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
            messages = json.loads(log.read_text())["log"]
            result["messages"] = messages
            result["exit_code"] = run.returncode
            completed = any("validated in" in m.get("message", {}).get("text", "") for m in messages)
            result["completed"] = completed
            result["engine_failure"] = any(
                "[Exception]" in str(m.get("message", "")) or
                m.get("code") in {"arelle:pluginLoadingError", "arelle:disclosureSystemName"}
                for m in messages)
            errors = any(m.get("level", "").lower() in ("error", "critical", "fatal") for m in messages)
            evidence = []
            for m in messages:
                if m.get("code") == "KVK.validationEvidence":
                    # addToLog includes a decorated text and the raw format args.
                    raw = m.get("message", {}).get("text", "")
                    start, end = raw.find('{'), raw.rfind('}')
                    evidence.append(json.loads(raw[start:end + 1]))
            result["assertion_evidence"] = evidence
            clean_evidence = bool(evidence) and all(not e["errors"] and not e["controller_errors"] for e in evidence)
            assertion_only_exit = (run.returncode == 3 and clean_evidence and any(e["assertions"] for e in evidence))
            result["technical_valid"] = (run.returncode == 0 or assertion_only_exit) and completed and not errors and not result["engine_failure"] and clean_evidence
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
