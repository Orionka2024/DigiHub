"""Provider-neutral handoff evidence and direct connection prerequisites.

No transmission is performed here. WUS requires a qualified signing/verifying
client as well as TLS; a generic HTTP POST is not a Digipoort implementation.
"""
from hashlib import sha256
import io
import json
import os
import zipfile


def readiness():
    return {
        "production_enabled": False,
        "provider": {"name": os.environ.get("KVK_SUBMISSION_PROVIDER", ""),
                     "mode": "manual_handoff", "api_connected": False},
        "direct": {
            "protocol": "WUS 1.3 (KVK groot iXBRL only)",
            "environment": "preproduction", "connected": False,
            "submission_endpoint": "https://wus.preproductie.digipoort.logius.nl/wus/2.0/aanleverservice/1.3",
            "status_endpoint": "https://wus.preproductie.digipoort.logius.nl/wus/2.0/statusinformatieservice/1.3",
            "required": ["Official WSDL and message type for the selected filing",
                         "Organization certificate and private key in protected credential storage",
                         "WS-Security request signing and response signature verification",
                         "Preproduction acceptance and final KVK processing status tests"],
        },
        "release_policy": "Manual qualification after final taxonomy and applicable 2026 rules are available; no automatic date-based activation.",
    }


def create_handoff(package, snapshot, taxonomy):
    """Outer transfer bundle; only report.zip is a candidate gateway payload."""
    evidence = {
        "schema_version": 1, "filing_id": snapshot.filing_id,
        "payload": "report.zip", "payload_sha256": sha256(package).hexdigest(),
        "source_sha256": snapshot.document_sha256, "snapshot_sha256": snapshot.frozen_digest,
        "xhtml_sha256": snapshot.validation_digest, "taxonomy_id": taxonomy.id,
        "taxonomy_sha256": taxonomy.sha256, "submitted": False,
        "provider_acceptance_confirmed": False,
        "instructions": "Give report.zip to the provider. This outer bundle is not a Digipoort payload. Confirm route, accepted format and attachments before submission; retain final processing receipt.",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.zip", package)
        archive.writestr("handoff.json", json.dumps(evidence, indent=2, sort_keys=True))
    return output.getvalue()


def create_audit_bundle(package, snapshot, taxonomy, *, document, validation_results, change_history):
    """Auditor evidence bundle. Hashes establish integrity, not digital signatures."""
    from dataclasses import asdict
    from app.store import _snapshot_to_dict, _default_serialiser
    from validator import validate_snapshot
    from accounting_controls import taxonomy_reconciliations
    from models import FilingState
    snapshot.verify_frozen()
    if snapshot.state != FilingState.VALIDATED:
        raise ValueError("Only an unchanged validated filing can enter the review handoff.")
    if document.sha256 != snapshot.document_sha256:
        raise ValueError("Source document does not match the frozen filing.")
    payload_digest = sha256(package).hexdigest()
    if validation_results.get("sha256") != payload_digest:
        raise ValueError("Validation evidence must identify these exact report-package bytes.")
    if not validation_results.get("technical_valid"):
        raise ValueError("Independent package validation has not passed.")
    with zipfile.ZipFile(io.BytesIO(package)) as report:
        instances = [n for n in report.namelist() if n.endswith('.xhtml')]
        if len(instances) != 1 or sha256(report.read(instances[0])).hexdigest() != snapshot.validation_digest:
            raise ValueError("Report instance differs from the validated frozen output.")
    saved = _snapshot_to_dict(snapshot)
    issues = [asdict(i) for i in validate_snapshot(snapshot, taxonomy)]
    def encode(value):
        return json.dumps(value, default=_default_serialiser, sort_keys=True, indent=2).encode()
    files = {
        "report.zip": package,
        "snapshot.json": encode(saved),
        "source-extraction.json": encode(asdict(document)),
        "mappings.json": encode({"facts": saved["facts"], "contexts": saved["contexts"], "units": saved["units"]}),
        "reconciliations.json": encode({"coverage": "available taxonomy calculations and structural/duplicate checks; not comprehensive accounting approval", "checks": taxonomy_reconciliations(snapshot, taxonomy), "issues": issues}),
        "validation_results.json": encode(validation_results),
        "change_history.json": encode(change_history),
        "warning_dispositions.json": encode(snapshot.warning_dispositions),
    }
    manifest = {"schema_version": 1, "status": "ready_for_external_review", "submitted": False,
                "filing_id": snapshot.filing_id, "profile_id": snapshot.profile_id,
                "source_sha256": snapshot.document_sha256, "snapshot_sha256": snapshot.frozen_digest,
                "taxonomy_id": taxonomy.id, "taxonomy_sha256": taxonomy.sha256,
                "rules_version": snapshot.rules_version, "digital_signatures": [],
                "limitations": ["Authenticated review records are not cryptographic signatures.",
                                "The original DOCX must accompany review separately; verify its source hash.",
                                "External accountant review is required; this is not submission evidence."],
                "files": {name: sha256(content).hexdigest() for name, content in files.items()}}
    files["manifest.json"] = encode(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, content)
    return output.getvalue()
