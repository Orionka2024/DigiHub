# Bug-fix verification — started 13 September, completed 14 September 2026

This repair addresses the implementation defects identified in the original audit. Existing filing data and taxonomy assets were not rewritten. The original audit remains a historical record of the pre-fix state.

## Repaired

1. Unified generator/service string handling, added source-backed rendering and a taxonomy schema reference, corrected the resources structure, and updated ZIP metadata/layout. Package construction finishes before state becomes validated. Unchanged validated filings can be downloaded again.
2. Freeze/export now block error issues. API diagnostics preserve severity, concept and rule reference. Incomplete independent validation blocks export explicitly.
3. Removed directory checksum bypass. Missing packages are rejected; unverified directories are separate preparation previews. Health reports verification, parsing errors and entry-point load status.
4. Fixed namespace extraction with lxml, file-qualified locator identity, per-entry-point parser state, include traversal, strict missing-dependency errors and duplicate rule indexing. Entry points load on demand, avoiding parsing every package profile on startup.
5. Added source-cell/context/unit-specific fact IDs and atomic mapping replacement. Failed requests do not leave contexts or units behind.
6. Preserved locale-specific decimal values. Replaced unchecked bulk recommendation writes with individual review through the mapping form. Fixed the undefined parentNodeId, boolean true-to-false conversion, ignored decimals and mismatched context IDs.
7. Added local weighted calculation checks with precision tolerance, stronger basic type/entity/provenance checks and mandatory-section enforcement. Conditional requirements require review. Full dimensional/formula validation remains an explicit external requirement.
8. Bound provenance to a real source coordinate and stored original extracted text independently from the approved fact value. Export checks it against the source document.
9. Preserved typed values and sign-off metadata on save/load; included extracted source in new saves; added atomic, per-filing persistence. Legacy frozen/validated saves without a content digest reopen as drafts requiring new review.
10. Restored browser mappings on load and preserved the filing ID during source reattachment. Added an explicit reopen action that clears validation evidence. Prevented local entity edits from diverging from an existing server filing.
11. Fixed the checklist model import and exposed checklist loading failures.
12. Deserialized entry-point metadata into typed records and rejected incompatible profile selections instead of substituting another profile.

Recovery checks also cover missing source documents, malformed uploads, conditional review completion, frozen control state, a save-before-reset New filing action, and taxonomy loading failures. The launcher reuses installed dependencies without contacting package indexes on every start.

Additional corrections include relative API URLs, escaped metadata in the admin UI, no fabricated KVK lookup results, bounded DOCX upload/expansion sizes, and maintained test discovery configuration.

## Verification

- Maintained Python regression suite: **43 passed**, including API upload/map/save/load/freeze, export rejection, package generation with an explicitly injected test validator, data types, mapping identity, parser isolation, sums, reopen and repeat download.
- JavaScript regression checks: amount formats, manual boolean/cell mapping, non-calendar comparative dates, restore and source reattachment.
- JavaScript syntax checks pass for workspace and admin code.
- Actual supplied micro taxonomy preview: **5,200 concepts, 76 rules, 13 recorded dependency errors**. This exercised the real package, not only fixtures. Its missing catalog dependencies are now visible instead of silently treated as complete.
- Two test-tool deprecation warnings remain in the installed Starlette/httpx/AnyIO combination; they do not cause failures.

## Remaining readiness limits

No independent DTS/formula/filing-rule validator is installed, and the supplied directory taxonomy is not a verified final package. Export remains intentionally blocked until these prerequisites are met. `KVK_VALIDATOR=module:function` is the integration point for a deployment-provided validator; the test stubs must never be used for production validation.

Source rendering preserves extracted text and table order but does not reproduce full Word layout, embedded images or other unsupported structures. No official conformance suite, live KVK API, Digipoort submission, penetration test or complete real-browser journey was run. Reviewer identity is still local/client-supplied; enterprise authentication and audit controls are not implemented by this repair.
