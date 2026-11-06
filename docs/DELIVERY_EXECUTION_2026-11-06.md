# 2025 iXBRL delivery implementation and remaining acceptance gates

Scope: prepare a report for an external audit firm's review and separate submission.
No submission client, production deployment or KVK acceptance claim is included.

**Status: implementation foundation delivered; production qualification is incomplete.**
The 2025 export route intentionally remains blocked. Do not remove that gate to
make an auditor download succeed before completing the remaining work below.

## Requirements baseline and corrections to the supplied blueprint

- [KVK 2025 resources](https://www.sbr-nl.nl/sbr-domeinen/handelsregister/documentatie-boekjaar-2025-kvk), including the Reporting Manual dated 31 October 2025 with errata through 12 February 2026.
- The downloaded official 2025 suite contains **237 variations**, declared in XML
  indexes. NT21 `instances_*` fixtures are a different format/year and cannot
  qualify this route.
- Initial profiles describe application scope, not legal eligibility. 2024,
  specialized sectors and IFRS for SMEs are not declared supported by inference.
- Dimensions remain on Context, their authoritative XBRL location. Duplicating
  them on Fact would create two potentially conflicting representations.
- Restated comparatives require explanations, not forced agreement with prior
  published amounts. Profit and cash-flow formulas need approved, profile-specific
  bindings; generic equations inferred from English labels are unsafe.
- Hashes and authenticated review identities are not digital signatures.
- 2025 iXBRL contexts use `xbrli:scenario`, not `xbrli:segment` (RM 3.1.3).

## Phase status

| Phase | Implemented | Still required for acceptance |
|---|---|---|
| 1: profiles | Candidate catalog/API, explicit 2025 selection, year/framework/entry-point checks, unsupported combination rejection, UI selection | Accountant approval of supported scope; qualification per supported profile. Specialized sectors and 2024 are excluded from this initial scope. |
| 2: taxonomies | Official KVK/RJ/BW2/NCGC/WNT/WW/IFRS-wrapper packages, LEI dependency, locally packaged unmodified enumeration schema; archive checksums and source provenance; dependency-aware offline resolver; filing version/hash/rule/dependency pinning | IFRS Foundation underlying taxonomy and IFRS qualification. Core standard schemas currently come from the pinned Arelle distribution and need inclusion in the final reproducible release inventory. |
| 3: mapping | Explicit scale, canonical sign, source number format, authenticated reviewer and UTC review time; persistence and UI support; original source remains unchanged; dimensions retained in Context | Approved accounting reference mappings; explicit span/block tagging, extensions and more complex presentation cases. Source and entry number formats are separate controls. |
| 4: controls | Semantic-context duplicate/conflict detection; taxonomy calculation evidence with inputs/difference/tolerance/incomplete status; rounding review warnings; stale-warning decision invalidation; warning review API/UI; explicit equation and comparative comparison helpers | Profile-specific balance-sheet/cash-flow/profit rules and coverage, approved bindings, prior-filing selection and restatement workflow. Helpers alone do not establish comprehensive accounting controls. |
| 5: generator | Tags in original paragraphs/cells; preserved numeric source strings with transformations; no inferred thousands scaling; value/scale/sign checks; scenario dimensions; unsupported Word-content detection and export blocking | Extension-taxonomy construction, companion filing-document requirements, constrained `.xbri` packaging, full source presentation fidelity, approved handling of nested/block tags and unsupported Word features. Existing generic ZIP output is not promoted to a compliant 2025 `.xbri`. |
| 6: independent validation | Official-suite runner checks declared error codes; offline NL plug-in; full package diagnostics; assertion-result evidence; engine/plugin/package hashes; positive and negative smoke cases | Complete 237-case run, manual cases, any remaining engine/profile failures, validator version qualification and regression baseline on generated reports. |
| 7: audit handoff | API and UI bundle entry point; exact-payload validation binding; snapshot, extraction, mappings, calculations, warnings, diagnostics, history and per-file hashes | Usable production handoff awaits phases 4–6. Original DOCX is not stored in this bundle and must be supplied separately with matching hash. No cryptographic signatures are claimed. |

## Observed qualification evidence

- The NL-GAAP 2025 entry point resolves offline with **6,462 concepts**, after
  adding dependency catalogs and the missing standard schema.
- The official positive case `G3-1-2_1/TC1_valid` passes technical validation.
- The official negative case `G3-1-2_1/TC2_invalid` produces the expected
  `periodWithTimeContent` error and is counted as a passing negative test.
- These are **2 of 237** variations. They are infrastructure smoke evidence, not
  completion of the conformance suite or approval of generated customer reports.
- Local regression results: see the final verification reported with this change.

The run identified and fixed three issues hidden by metadata-only readiness:
missing `tinycss2` prevented the NL plug-in from importing; missing LEI prevented
offline DTS loading; explicit `--formula run` caused an Arelle 2.45 plug-in crash.
The adapter now uses normal `--validate` formula execution. Arelle also puts
successful formula result dictionaries into `model.errors`, producing exit 3
without a validation error. A read-only plug-in records assertion counts and
real error codes; only clean, completed assertion evidence can distinguish this
case. Unknown results, unsatisfied assertions, engine exceptions and missing
dependencies remain failures.

## Reproduction

Download inventory and observed SHA-256 values: `docs/KVK_2025_DOWNLOADS.json`.
The large conformance ZIP is stored locally under ignored
`data/qualification/2025/conformance-suite.zip`, not bundled into the application.
The smaller taxonomy archives and manifest are under `app/data/taxonomies/`.
The enumeration support ZIP is a local wrapper, explicitly distinguished from
publisher-supplied archives in the inventory.

```bash
app/.venv/bin/python -m pip install -r app/requirements-validator.txt
app/.venv/bin/python -m pytest -q
node tests/workspace.test.cjs
app/.venv/bin/python conformance.py \
  --suite data/qualification/2025/conformance-suite.zip \
  --packages app/data/taxonomies \
  --output data/qualification/2025/smoke-results.json --limit 2
```

Omit `--limit 2` for the full suite. Each case has a bounded validator subprocess.
The runner does not automatically activate an export profile, even after all
automated cases pass. Manual review cases remain explicit outstanding work.

## Next implementation sequence

1. Choose one initial supported profile with the accountant and obtain an approved
   source report plus expected facts, periods, units, scales, dimensions and
   disclosure decisions. Retain negative variants and restatement examples.
2. Implement and test that profile's accounting controls and completeness policy.
   Record checks that cannot be evaluated as incomplete, never passed.
3. Implement the extension and filing-document architecture against the official
   example for that profile; validate the complete `.xbri`, including attachments.
4. Complete the official suite and generated-report reference tests. Record exact
   engine/rules/dependency versions, expected failures and unresolved manual cases.
5. Enable audit handoff only for the qualified profile after the external reviewer
   verifies source fidelity and expected mappings. Keep unsupported profiles gated.

Legacy frozen snapshots without the new pinning metadata reopen as drafts and
lose prior approval/validation fields; they are not silently re-sealed. Existing
2026 beta work remains preparation-only. No actual company report was submitted.
