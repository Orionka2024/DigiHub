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
