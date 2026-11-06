from __future__ import annotations

from generator import generate_ixbrl
from models import FilingSnapshot, FilingState
from package import create_report_package
from registry import TaxonomyRegistry
from validator import validate_snapshot, validate_xml


class ExportBlocked(RuntimeError):
    pass


class FilingService:
    """Orchestrates only verified local construction; it never submits a filing."""

    def __init__(self, registry: TaxonomyRegistry, external_validator=None) -> None:
        self.registry = registry
        self.external_validator = external_validator

    def validate_and_package(self, snapshot: FilingSnapshot, document=None) -> bytes:
        if snapshot.state not in (FilingState.FROZEN, FilingState.VALIDATED):
            raise ExportBlocked("A filing must be reviewed and frozen before validation/export.")
        try:
            snapshot.verify_frozen()
        except ValueError as exc:
            raise ExportBlocked(str(exc)) from exc
        taxonomy = self.registry.get(snapshot.taxonomy_id)
        if not self.registry.is_active(taxonomy.id):
            raise ExportBlocked("The selected taxonomy has been deactivated.")
        if not taxonomy.package_verified:
            raise ExportBlocked("The selected taxonomy package has not been locally checksum-verified.")
        if hasattr(taxonomy, "complete_entry_points") and snapshot.entry_point_key not in taxonomy.complete_entry_points:
            raise ExportBlocked("DTS_INCOMPLETE: The selected entry point has unresolved or unloaded dependencies.")
        issues = validate_snapshot(snapshot, taxonomy)
        critical_issues = [issue for issue in issues if issue.severity in {'error', 'critical'}]
        if critical_issues:
            raise ExportBlocked("; ".join(f"{issue.code}: {issue.message}" for issue in critical_issues))
        if getattr(taxonomy, "reporting_year", 0) == 2025 and not snapshot.profile_id:
            raise ExportBlocked("PROFILE: A reviewed 2025 reporting profile is required.")
        if snapshot.profile_id:
            from accounting_controls import undisposed_warnings
            if undisposed_warnings(snapshot, issues):
                raise ExportBlocked("REVIEW: Every warning requires a current documented disposition.")
            # No production qualification is inferred from installing a taxonomy
            # or obtaining zero diagnostics. Extension generation and the complete
            # official conformance run must be qualified before this gate changes.
            raise ExportBlocked("QUALIFICATION_INCOMPLETE: 2025 extension taxonomy generation and complete package conformance are not qualified.")
        if self.external_validator is None:
            raise ExportBlocked("VALIDATION_INCOMPLETE: An independent DTS, formula and filing-rule validator must be configured before export.")
        if document is None or document.sha256 != snapshot.document_sha256:
            raise ExportBlocked("PROVENANCE: The exact source document is required for rendering.")
        if any(w.startswith("UNSUPPORTED_CONTENT:") for w in document.warnings):
            raise ExportBlocked("SOURCE_UNSUPPORTED: Remediate unsupported Word content before export.")
        from mapping import source_value
        for fact in snapshot.facts:
            matches = []
            for node in document.nodes:
                try:
                    matches.append(source_value(node, fact.source.location))
                except ValueError:
                    continue
            if fact.source.extracted_value not in matches:
                raise ExportBlocked("PROVENANCE: Source coordinates or extracted value do not match the document.")
        ixbrl = generate_ixbrl(snapshot, taxonomy.namespaces, entry_point=taxonomy.entry_point(snapshot.entry_point_key), document=document)
        xml_issues = validate_xml(ixbrl)
        if xml_issues:
            raise ExportBlocked("; ".join(f"{issue.code}: {issue.message}" for issue in xml_issues))
        external_issues = self.external_validator(ixbrl, snapshot, taxonomy)
        if external_issues is None:
            raise ExportBlocked("VALIDATION_INCOMPLETE: Independent validator returned no result.")
        if external_issues:
            raise ExportBlocked("; ".join(str(issue) for issue in external_issues))
        package = create_report_package(snapshot, taxonomy, ixbrl.encode("utf-8"))
        if snapshot.state == FilingState.FROZEN:
            snapshot.mark_validated(ixbrl)
        else:
            from hashlib import sha256
            if snapshot.validation_digest != sha256(ixbrl.encode()).hexdigest():
                raise ExportBlocked("Validated output changed. Reopen and review the filing again.")
        return package


def configured_external_validator():
    """Load a deployment-provided validator, never a client-supplied callback.

    KVK_VALIDATOR specifies an importable module:function. It must perform full
    DTS, dimensional, calculation, formula and applicable filing-rule validation
    of (ixbrl_text, snapshot, taxonomy), returning an empty list only on success.
    """
    import importlib
    import os
    spec = os.environ.get("KVK_VALIDATOR")
    if not spec:
        return None
    module, separator, name = spec.partition(":")
    if not separator or not module or not name:
        raise ValueError("KVK_VALIDATOR must be module:function.")
    callback = getattr(importlib.import_module(module), name)
    if not callable(callback):
        raise ValueError("KVK_VALIDATOR must name a callable.")
    return callback
