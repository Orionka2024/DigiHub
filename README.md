# KVK iXBRL preparation workspace

Local DOCX extraction, reviewed fact mapping, taxonomy browsing, workspace persistence and guarded report-package construction.

Run the application with `bash app/start.sh`. It binds to localhost and reuses installed dependencies. Set `INSTALL_DEPS=1` to reinstall the pinned runtime dependencies. The existing virtual environment can run the regression suite:

```bash
app/.venv/bin/python -m pytest -q
node tests/workspace.test.cjs
```

For a fresh development environment, install `app/requirements-dev.txt`. `pytest.ini` restricts collection to maintained tests; root-level `test_*.py` files are historical exploratory scripts.

## Current behavior

- Mapping preserves the exact source paragraph/cell text and separate reviewed value. Comparative periods have distinct fact identities.
- Numeric entry explicitly selects Dutch or English formatting. Recommendations require individual review of amount, context and unit.
- Saving preserves booleans, dates, decimals, sign-off and extracted source. Filings have separate files by entity, year and filing ID; writes are atomic. Existing legacy files remain readable and are not overwritten by new saves.
- Loading by KVK number selects the most recently saved filing. The API accepts `?filing_id=...` to select a specific filing. Re-uploading the same DOCX reattaches it to the existing filing.
- New filing saves the current workspace before opening a fresh one.
- Frozen content has a digest. Changes invalidate validation. Reopening clears sign-off and validation evidence.
- Taxonomy parsing isolates entry points and retains namespace identity. Missing dependencies are errors in strict mode. Directory previews expose incomplete dependency information through `/health`.
- Generated documents include extracted paragraphs/tables and a visible reviewed-facts table. This is a basic rendering, not a faithful Word layout conversion.

## Export prerequisites

The supplied directory taxonomy is available for **preparation only**. A local manifest's `final` field and an unhashed directory do not establish a verified release. The micro entry-point check found unresolved external schema dependencies in the supplied catalog.

Export requires a registered, checksum-verified final package, passing local checks, the matching source document, unchanged frozen content, and an independently implemented validator. Without that validator, export returns `VALIDATION_INCOMPLETE` instead of reporting success.

A deployment may set `KVK_VALIDATOR=module:function`. The callable receives `(ixbrl_text, snapshot, taxonomy)` and must perform complete DTS/schema, dimensional, calculation, formula and applicable filing-rule validation. It returns an empty list only on success, and issues otherwise. Arelle technical diagnostics are available through the optional pinned validator requirements; the supplied adapter deliberately does not authorize filing export. Test callbacks verify orchestration only; they are not compliance validators.

`KVK_TAXONOMY_DIR` optionally selects a different local taxonomy directory. Directory previews are never promoted to verified releases automatically. Taxonomy entry points load on demand through a background queue.

The ZIP layout uses a single top-level directory containing `META-INF/reportPackage.json` and `reports/`, consistent with the [Report Packages 1.0 specification](https://www.xbrl.org/Specification/report-package/REC-2023-09-22%2Bcorrected-errata-2025-03-11/report-package-REC-2023-09-22%2Bcorrected-errata-2025-03-11.html). This does not establish acceptance by KVK.

## Remaining product requirements

This is not a certified filing or submission service. Official release verification, full independent conformance testing, faithful rendering of unsupported Word content, authenticated reviewer identities, enterprise audit controls and a Digipoort adapter remain outside the implemented foundation. KVK lookup requires `KVK_API_KEY`; without it the API reports that lookup is unconfigured and never invents a company.

See `BUGFIX_REPORT_2026-09-13.md` for this repair's scope and verification, and `AUDIT_READINESS_2026-09-13.md` for the original audit.

## Preproduction additions (15 September 2026)

Arelle diagnostics, enriched verified ZIP loading, deterministic report payloads, provider handoff evidence and direct connection readiness are implemented. Neither provider API transport nor a signed Digipoort client is connected. See [TAXONOMY_SETUP.md](TAXONOMY_SETUP.md) for exact setup, API routes and remaining qualification steps. Production stays disabled until the applicable releases and integrations are qualified.

## Guided tagging review

Choose the company size/reporting profile explicitly for new filings. The Tagging review sidebar shows outstanding mandatory/conditional items from parsed rules by default; optional concepts remain searchable under All available tags. This is preparation guidance rather than an independent completeness determination.

Suggest tags for document scans table amounts using Dutch/English taxonomy labels. Review each suggested tag, amount, period, unit and scale, then confirm or skip. Already mapped source cells are excluded. Explicit year headings provide period hints; absent headings require the reviewer to choose a period. Suggestions are not saved until confirmed. Paragraph/text tagging remains manual.
