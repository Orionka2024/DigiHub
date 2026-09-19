# Taxonomy and submission preparation — 15 September 2026

The supplied `NT21_KVK_20261209.b` package is a beta. The loader now treats `.a`/`.b` versions as previews even if the local manifest says `final`. Do not relabel a beta to release a filing.

The [SBR release calendar](https://www.sbr-nl.nl/werken-met-sbr/taxonomie/releasekalender) schedules the final NT21 KVK publication for 29 October, final preproduction for 25 November and production for 9 December 2026. Confirm the actual release and accepted filing profile at rollout; dates never activate this application automatically.

## Installed preparation features

- Arelle 2.45.0 is installed in `app/.venv`. Reproduce with `app/.venv/bin/python -m pip install -r app/requirements-validator.txt`.
- **Arelle checks** downloads independent technical diagnostics for the open filing, without changing its review state. The matching API is `POST /api/snapshot/{filing_id}/independent-validation`.
- Checks run offline in a separate process with isolated configuration and a 120-second timeout. Missing dependencies remain errors. They do not silently download substitute taxonomies.
- The installed Netherlands plugin supports NT20 and 2025 inline profiles; it does not yet contain NT21 or a 2026 inline profile. Generic XBRL success is never presented as suitability for filing.
- `GET /api/submission/readiness` reports installed engine profiles, provider mode and direct connection prerequisites.
- **Provider handoff** calls the existing export gates, then bundles `report.zip` with `handoff.json`. The latter records the exact payload, source, frozen snapshot, XHTML and taxonomy hashes. The outer handoff ZIP is NOT the submission payload. Provider acceptance is not asserted.
- Repeated report generation is deterministic so that payload hashes remain stable for identical reviewed output.

## Installing a future final release

Obtain the official ZIP and release metadata from SBR/KVK for the exact reporting year, company class, framework and filing format. Traditional NT XBRL entry points and KVK iXBRL profiles are not interchangeable.

Place the ZIP and application manifest in `app/data/taxonomies/`, or the configured `KVK_TAXONOMY_DIR`. Set `package_file` to the archive filename and `sha256` to its independently checked SHA-256. Record the official release status and version accurately. Preserve entry-point metadata, namespaces and requirements.

ZIP loading checks the checksum, rejects path traversal, links, duplicate names and excessive expansion, and requires one `META-INF/taxonomyPackage.xml`. It builds an enriched release so that concepts and rules can be parsed, rather than registering only a lightweight checksum record. Entry-point paths are relative to the taxonomy package root, not its outer ZIP directory. Directories remain unverified previews.

Inspect `/health` and load each intended entry point. Exports from enriched releases remain blocked while its dependency parsing is incomplete. Supply official dependency packages/catalog mappings as required; a checksum does not establish a complete DTS or official provenance by itself.

## Validator qualification

Keep `KVK_VALIDATOR` unset until a complete validator is qualified. The optional `KVK_v2.arelle_validator:validate_report` adapter deliberately returns `VALIDATION_INCOMPLETE`: it is a diagnostic adapter, not a production approval bypass.

When the applicable 2026 rules become available, test the exact report package with its extension taxonomy and attachments using the correct disclosure profile, positive and negative official conformance fixtures, and the provider/preproduction environment. Pin the qualified engine/rule versions and retain the validation log and exact package hash. The current generator's basic Word rendering and supported report structure also need review against that profile.

## Provider and direct routes

Provider handoff is prepared now. Provider-specific upload/API mapping remains dependent on its name and documentation. Retain final processing receipts with the package hash; download or initial transport receipt is not confirmation of deposition.

Direct transport is NOT implemented yet. [Logius WUS 1.3 documentation](https://aansluiten.procesinfrastructuur.nl/site/nieuwe-digipoort/ixbrl-via-digipoort) specifies a separate interface for KVK groot iXBRL; other message types currently use WUS 1.2. Direct readiness exposes only the documented preproduction submission/status URLs. Implementation requires the official WSDL/message type, organization test or PKIoverheid credentials, TLS trust chain, WS-Security signing and response verification, and status handling tested end to end. Do not send a ZIP using a generic HTTP POST.

The user must arrange certificate access through protected credential storage, not this document or source code. No filing has been transmitted and no automatic production activation has been added. The local app also still needs authentication and production operational controls before network deployment.
