# KVK_v2 readiness and correctness audit

Date: 13 September 2026. Verdict: **not ready for production or filing use; the end-to-end preparation/export workflow is also currently broken.**

This review inspected the Python core, FastAPI routes, workspace persistence, browser workflow, active taxonomy parser, rules engine, dependency/launch configuration, and maintained tests. It used the existing virtual environment and isolated synthetic inputs. Application code and existing filing data were not changed. This directory is not a Git repository, so no commit baseline or historical diff was available.

The bundled taxonomy/reference corpus was not exhaustively validated. No live KVK lookup, submission, full browser journey, clean-environment dependency installation, or official conformance suite was run. This is a software audit, not certification of regulatory compliance.

## Verification results

| Check | Observed result |
|---|---|
| `PYTHONPATH=.. app/.venv/bin/python -m pytest tests -q` | **4 failed, 1 passed, 1 skipped, 4 setup errors** |
| Documented unittest discovery, using existing venv | **5 tests run: 1 passed, 4 errors** |
| Python AST syntax check | 59 project/test/utility Python files parsed without syntax errors |
| `node --check` for workspace.js and admin.js | Both passed |
| Export service, synthetic frozen snapshot | `TypeError: 'TaxonomyRelease' object is not iterable` |
| Mapping current/prior year from same table | Identical fact IDs |
| Auto-tagging `1.234,56` | Returned `123456` |
| Persistence round trip | Approval fields lost; boolean `True` became string `'True'` |
| Invalid source hash and mismatched context entity | Validator returned no issues when other metadata was populated |
| Entry-point selection with loader-shaped metadata | `AttributeError: 'dict' object has no attribute 'company_class'` |
| Checklist route body with a populated synthetic taxonomy | `NameError: name 'ChecklistItemOut' is not defined` |
| Two independent synthetic taxonomy schemas | First schema's concept incorrectly assigned to second entry point |

The route-body reproduction executed the existing function extracted from its AST, with a synthetic registry; it did not start the application or its background taxonomy loader. The test skip is not evidence that the bundled taxonomy is unavailable: the test looks in a different directory from the application.

## Findings

### 1. P1 — Export cannot complete because service and generator contracts disagree

Location: [service.py:30](/Users/aleksandrkim/Documents/KVK_v2/service.py:30), [generator.py:65](/Users/aleksandrkim/Documents/KVK_v2/generator.py:65).

The service passes a taxonomy release as the generator's second argument. The generator expects a namespace dictionary and calls `ns.update(...)`, producing the reproduced TypeError. Even after correcting that argument, the service calls `.decode()` on the generator's string result at line 34, causing another exception. The HTTP export handler turns these into a 500 response.

Required correction: agree on the generation input and text/bytes boundary, and cover the real service-to-ZIP path with an integration test. Do not mark a snapshot validated until package construction has succeeded.

### 2. P1 — Freeze and export ignore validation errors

Location: [service.py:27](/Users/aleksandrkim/Documents/KVK_v2/service.py:27), [app/main.py:701](/Users/aleksandrkim/Documents/KVK_v2/app/main.py:701), [validator.py:40](/Users/aleksandrkim/Documents/KVK_v2/validator.py:40).

Validation issues use `error`, `warning`, and `info`, while both gates block only `critical`. An empty snapshot produced `SBR-004` and `SBR-005` errors but reached generation instead of raising ExportBlocked. Current generator crashes mask this bypass; fixing generation alone would expose it.

The diagnostics endpoint also drops actual severity, concept, and rule reference when constructing its response. The API model consequently labels every issue `critical`, including warnings.

Required correction: define one shared severity contract and prove that missing mandatory facts, missing contexts, and invalid concepts prevent both freezing and export.

### 3. P1 — Taxonomy checksum verification can be bypassed

Location: [app/main.py:84](/Users/aleksandrkim/Documents/KVK_v2/app/main.py:84), [registry.py:202](/Users/aleksandrkim/Documents/KVK_v2/registry.py:202).

Any package path that is not a file enters an `else` branch setting `package_verified=True` and `sha256='directory-no-hash'`. This includes directories without integrity verification and nonexistent paths. The registry explicitly accepts this sentinel. Release finality is taken from the local manifest, rather than established by verification of trusted release metadata.

The installed manifest identifies a `20261209.b` package as final; associated example filenames say NT21beta. That discrepancy needs authoritative resolution before use, rather than treating the local `final` field as proof.

Required correction: require an existing verified package, bind the extracted directory to the verified archive/file inventory, and reject missing or altered content. Readiness must reflect completion of the selected entry point's parsing and verification.

### 4. P1 — Parser loses namespace identity and contaminates entry-point membership

Location: [taxonomy_parser.py:223](/Users/aleksandrkim/Documents/KVK_v2/taxonomy_parser.py:223), [taxonomy_parser.py:150](/Users/aleksandrkim/Documents/KVK_v2/taxonomy_parser.py:150), [taxonomy_parser.py:713](/Users/aleksandrkim/Documents/KVK_v2/taxonomy_parser.py:713).

The active parser uses ElementTree but searches `root.attrib` for namespace declarations. Those declarations are not retained there, so the URI-to-prefix map remains empty and concepts are stored by bare local name. Distinct namespaces can collide, and prefixed rule concept names need not match stored concepts.

Separately, the parser accumulates concepts across entry points and assigns every accumulated concept to each new entry point. Two independent schemas reproduced `A: ['ep-a', 'ep-b']` despite B's schema not importing A. The shared visited-file cache also prevents revisiting shared formula files to establish their applicability to later entry points.

Missing or unreadable schema files return silently, and concept validation skips membership checks when the entry-point concept set is empty.

Required correction: retain expanded QName identity and an explicit dependency graph per entry point. Cache parsed files separately from entry-point membership, and reject incomplete resolution.

### 5. P1 — Mapping comparative facts silently overwrites existing facts

Location: [mapping.py:30](/Users/aleksandrkim/Documents/KVK_v2/mapping.py:30), [app/main.py:617](/Users/aleksandrkim/Documents/KVK_v2/app/main.py:617).

A fact ID consists only of source node ID and concept QName. Both columns of a financial table use the parent table node, so current-year and prior-year values for the same concept receive the same ID. The mapping endpoint removes the first fact when adding the second. The browser can still display both cell mappings.

Required correction: use stable mapping identities that distinguish source cell, context, and relevant aspects; replace a fact only when explicitly editing that mapping. Verify that two comparative periods remain in the exported instance.

### 6. P1 — Auto-tagging changes monetary values and assumes the period

Location: [autotagger.py:68](/Users/aleksandrkim/Documents/KVK_v2/autotagger.py:68), [app/frontend/workspace.js:1060](/Users/aleksandrkim/Documents/KVK_v2/app/frontend/workspace.js:1060).

Removing every dot and comma converts the Dutch decimal `1.234,56` to `123456`. The browser applies all recommendations with a current-year duration context, EUR, and zero decimals, including concepts that may require an instant or another period. It also ignores mapping HTTP response status and records success locally after rejected requests.

Required correction: parse numeric formats explicitly, preserve precision, require appropriate period/unit selection, and only update the UI after a successful server response.

### 7. P1 — Claimed validation coverage exceeds implemented checks

Location: [validator.py:339](/Users/aleksandrkim/Documents/KVK_v2/validator.py:339), [validator.py:375](/Users/aleksandrkim/Documents/KVK_v2/validator.py:375), [validator.py:76](/Users/aleksandrkim/Documents/KVK_v2/validator.py:76).

Calculation validation computes a child contribution but never compares totals or emits an issue. Value assertions are skipped; no dimension/hypercube validation is invoked. XML validation only parses for well-formedness. Legacy conditional requirements are skipped, required report sections are unchecked, and a reviewed ID can waive a missing unconditional legacy fact. Presence checks do not distinguish reporting contexts.

Required correction: implement or integrate the actual schema/DTS, dimensional, calculation, and formula checks. Clearly report unsupported validation as incomplete, with export blocked where required. Test deliberately invalid totals, dimensions, types, and mandatory contexts.

### 8. P1 — Source provenance and entity binding are not enforced by validation

Location: [mapping.py:24](/Users/aleksandrkim/Documents/KVK_v2/mapping.py:24), [validator.py:53](/Users/aleksandrkim/Documents/KVK_v2/validator.py:53).

Mapping only verifies that a parent node exists and a reviewer string is nonempty. Arbitrary source locations and values can be supplied, and `extracted_value` is filled from the submitted value rather than the referenced source. The validator does not compare source hashes, verify review evidence, or bind context entity identity/scheme to the filing. An isolated snapshot with a wrong fact source hash, no reviewer, and a different context entity passed with zero issues.

Required correction: bind facts to real source coordinates and immutable extraction evidence; record approved transformations separately. Validate source hash, reviewer evidence, and entity consistency at the export boundary.

### 9. P1 — Generated output omits the report and selected taxonomy reference

Location: [generator.py:115](/Users/aleksandrkim/Documents/KVK_v2/generator.py:115), [generator.py:186](/Users/aleksandrkim/Documents/KVK_v2/generator.py:186).

The generator puts every fact in `ix:hidden`, emits an empty `ix:references`, wraps contexts/units in `xbrli:xbrl`, and renders only an entity heading plus placeholder explanatory text. It does not render the source report or insert the selected entry point as a schema reference. A generated document without any schemaRef passed the local XML check.

The Inline XBRL specification defines the references content and resources structure; simple XML parsing does not establish conformity. See the [official Inline XBRL 1.1 specification](https://www.xbrl.org/Specification/inlineXBRL-part1/REC-2013-11-18%2Berrata-2026-07-14/inlineXBRL-part1-REC-2013-11-18%2Bcorrected-errata-2026-07-14.html), sections 12 and 14.

Required correction: render the reviewed report with its facts and correct taxonomy references, then validate the generated output and package with an independent conformant processor and applicable filing tests.

### 10. P1 — Workspace recovery loses metadata and redirects users to a new filing

Location: [app/store.py:34](/Users/aleksandrkim/Documents/KVK_v2/app/store.py:34), [app/store.py:79](/Users/aleksandrkim/Documents/KVK_v2/app/store.py:79), [app/frontend/workspace.js:347](/Users/aleksandrkim/Documents/KVK_v2/app/frontend/workspace.js:347), [app/frontend/workspace.js:966](/Users/aleksandrkim/Documents/KVK_v2/app/frontend/workspace.js:966).

Serialization omits final status, signatory, and approval date. Every value becomes text, but loading restores only numeric types. Boolean True becomes `'True'`, which the generator will no longer render through its boolean branch. Frozen/validated state remains despite the changed data.

After loading, the UI asks the user to re-upload the source DOCX. Upload unconditionally clears local mappings and creates a new empty snapshot, replacing the loaded filing ID in the active UI. Existing backend facts are not immediately deleted, but the resumed workflow loses access to them and a later save can overwrite the saved workspace. Files are also keyed only by KVK number, allowing another reporting year to replace the earlier workspace.

Required correction: preserve all typed fields, retain the loaded filing during matching-source reattachment, return full mapping details, and key persisted filings by entity plus period/filing ID. Use atomic writes.

### 11. P1 — Checklist fails for populated results

Location: [app/main.py:437](/Users/aleksandrkim/Documents/KVK_v2/app/main.py:437).

`ChecklistItemOut` is used without an import. A populated checklist raises the reproduced NameError; empty results can conceal it. The frontend silently ignores non-success responses, so the required-tag view can remain empty.

Required correction: import the model, expose failures to the user, and test a populated checklist through the actual API.

### 12. P2 — Entry-point selector receives dictionaries but expects dataclasses

Location: [app/main.py:95](/Users/aleksandrkim/Documents/KVK_v2/app/main.py:95), [registry.py:157](/Users/aleksandrkim/Documents/KVK_v2/registry.py:157).

The loader stores raw dictionaries in entry_point_meta. Selection accesses `.company_class`, `.sector`, `.framework`, and `.key`, producing an AttributeError. The `consolidated` argument is also ignored and selection falls back to the highest score without rejecting unsupported profiles.

Required correction: deserialize to EntryPointMeta including the key and validate all requested profile dimensions. Do not silently substitute an incompatible entry point.

## Operational and test readiness gaps

- Maintained tests are out of sync with production contracts: legacy requirements are tuples in core fixtures but dictionaries in the validator; validator fixtures use an invalid source hash. Repairing fixtures alone will not fix the product defects above.
- The importer test points to `app/data/...` instead of `app/data/taxonomies/...`, skips, and assumes the wrong return type. No maintained end-to-end API/browser regression coverage was found in `tests/`.
- The application has no authenticated identity or authorization layer. Reviewer names are client-supplied strings. This is insufficient for a shared review workflow; the launcher currently binds to loopback.
- Snapshot freeze is a mutable state marker, not an immutable content snapshot. Direct callers retain mutable lists and metadata. Validation evidence is not bound to a canonical source/taxonomy/snapshot digest.
- Health reports readiness from registry presence while entry points continue loading in a background thread. Missing schema resolution and background failures do not reliably prevent a ready signal.
- KVK lookup returns fabricated company records for arbitrary eight-digit inputs without an API key. Mock mode must not be mistaken for verified identity.
- DOCX uploads are read in full without an application size limit. The extractor warns about some unsupported content, but those warnings have no enforced review gate.
- The folder mixes application code, patch scripts, exploratory tests, a local virtual environment, and multiple taxonomy copies. There is no Git baseline here. Reproducible packaging, deployment, backup/recovery, and dependency security were not established by this audit.

## Release acceptance sequence

1. Restore error blocking and repair the export contract together. Prove invalid input cannot reach successful packaging.
2. Fix fact identity, decimal parsing, provenance checks, and complete typed workspace recovery. Cover comparative periods and reload/re-upload flows.
3. Repair QName handling and entry-point isolation; enforce verified complete taxonomy loading and repair checklist/selector APIs.
4. Implement complete report rendering and independent XBRL/iXBRL validation. Run official positive/negative fixtures and applicable conformance suites.
5. Add API/browser workflow tests, canonical immutable validation evidence, reliable persistence, and identity controls appropriate to the intended deployment.

Completion should be demonstrated by a real DOCX → reviewed mappings → save/restart/reload → freeze → validated package workflow, with source values, comparative facts, approvals, and taxonomy identity preserved. All negative fixtures must be rejected for the intended reasons.
