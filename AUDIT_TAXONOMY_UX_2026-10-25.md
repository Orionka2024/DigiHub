# Taxonomy and first-time filer audit — 25 October 2026

## Assessment

The application is a preparation workspace, not yet a dependable end-to-end filing service for an inexperienced user. Keep real filing use gated until the authentication, persistence, taxonomy loading and validation issues below are resolved. English-first guidance and a guided workflow should follow these correctness fixes.

Scope: current local source at commit `00864ac` plus the existing working tree, bundled taxonomy manifest, isolated reproductions, maintained tests, and current official SBR/KVK publications. No production accounts, customer filings or production database were accessed. This is not an independent regulatory certification or a concept-by-concept comparison of the new iXBRL taxonomy. Browser verification is recorded separately below; code-derived UX observations should not be mistaken for usability testing with a real first-time filer.

Browser limitation: localhost binding was denied in the sandbox. The subsequent request to run an isolated local preview server outside that restriction was rejected because automatic approval review timed out. No authenticated browser walkthrough or visual layout verification was completed. No application implementation was changed; this audit document is the deliverable.

## Latest taxonomy: distinguish the reporting formats

The bundled manifest `app/data/taxonomies/nt21_kvk.json` identifies `NT21_KVK_20261209_b`, version `20261209.b`, status `beta`. Its entry points are the predefined NT21 annual-report profiles. The app generates inline XBRL, so suitability of those entry points for its intended iXBRL filing route must be established explicitly. Selecting a taxonomy merely because its year is newer is insufficient.

Official information checked on 25 October 2026:

- SBR announced the separate **NTiXBRL_KVK_20261231 alpha on 22 October 2026**. It is available for assessment, not automatic promotion to production. [Announcement](https://www.sbr-nl.nl/alfaversie-van-ntixbrlkvk20261231-gepubliceerd).
- The 2026 iXBRL documentation lists separate KVK, RJ, BW2 Title 9, NCGC, WNT, WW and IFRS packages. Qualify the dependencies applicable to the selected reporting framework. [2026 documentation](https://www.sbr-nl.nl/sbr-domeinen/handelsregister/documentatie-boekjaar-2026).
- The release calendar schedules NT21 KVK final publication for **29 October**, production implementation for **9 December**. The separate iXBRL final is provisionally scheduled for **21 December**, production implementation for **31 December**. These are plans, not evidence that a release is already usable. [Release calendar](https://www.sbr-nl.nl/werken-met-sbr/taxonomie/releasekalender).
- The alpha announcement flags a proposed report-package maximum reduction from **100 MB to 50 MB**, with the documentation changes still being worked on. Track and qualify the final rule; do not silently treat the announcement as an already effective universal limit. `package.py` has no output-size policy today. Input DOCX limits are a separate concern. [Announcement](https://www.sbr-nl.nl/alfaversie-van-ntixbrlkvk20261231-gepubliceerd).
- Final 2025 iXBRL packages, reporting documentation, examples and a conformance suite are available. Use an explicit supported-year/format/framework matrix when qualifying current production filing, rather than forcing every filing onto the 2026 beta. [2025 documentation](https://www.sbr-nl.nl/sbr-domeinen/handelsregister/documentatie-boekjaar-2025-kvk).

Required release record: official source URL, release identifier, alpha/beta/final status, publication date, production availability, checksum, applicable filing formats and reporting frameworks, dependency packages, rules/manual versions and conformance results. Keep the release immutable per filing. Offer an explicit migration with a changed/deprecated-concept report and renewed review when necessary. Preserve the existing rejection of beta export.

## Findings requiring correction before real filing use

### 1. Critical: authentication fallback can accept a marker as a password

Evidence: `app/auth.py:36` accepts a plaintext match; `app/auth.py:129` stores the literal marker `supabase_auth` for synced Supabase-authenticated users. The fallback login path reads that value as password material. An isolated call confirmed that the verifier accepts the marker as its own password. This establishes the code defect, not that a production account has been exploited.

Update: separate authentication providers; never store a provider marker in a password-verifier field. Remove plaintext acceptance, make provider-authenticated accounts ineligible for local-password fallback, and fail production startup when the signing secret is the development default. Use separate Supabase clients for administrative data access and user authentication rather than mutating one shared client's auth state. Add negative login tests and verify account/session revocation behaviour.

Acceptance: knowing an email and the marker cannot authenticate; invalid or removed users fail closed; concurrent sign-ins cannot alter another request's database authorization.

### 2. High: a taxonomy update can load the previous package's contents

Evidence: `taxonomy_package.py:16–19` verifies the requested ZIP, then returns the first existing extracted package anywhere in the shared extraction destination. It does not associate that directory with the requested checksum. A temporary two-package reproduction returned the old metadata after the new archive passed verification.

Update: cache by archive digest; verify cache identity and completion; extract atomically; isolate releases and dependencies; coordinate concurrent extraction. Never label files from one release with another release's verified checksum.

Acceptance: loading A, then B, then A yields the correct bytes each time; parallel loads and interrupted extraction cannot return partial or mismatched content.

### 3. High: successful save can be non-durable

Evidence: `app/store.py:214` falls back to memory when Supabase is unavailable. `save_to_disk` at line 361 returns a synthetic path without writing a file; the save API reports success, and `workspace.js:1360` displays “Workspace saved”. In a database-free reproduction, save returned normally, no file existed, and immediate load raised `FileNotFoundError`.

Update: production writes must fail clearly without confirmed durable storage. Provide an explicitly labelled local demo mode if needed. Show last confirmed save time, unsaved changes, retry/recovery and a list of saved filings by company, year and status. Prevent starting another filing from discarding work that was never durably saved. Review stale cache fallback after database errors and introduce version checks for concurrent edits.

Acceptance: a confirmed save survives process restart and another authenticated session; a database outage produces an actionable error instead of a success message.

### 4. High: authentication is not filing ownership or reviewer authorization

Evidence: middleware checks login, but filing store queries are by filing ID/KVK number without owner membership checks. The migration leaves RLS commented out and `created_by` is not populated by `WorkspaceStore.add`. Admin activation routes at `app/main.py:313` and 321 have no role check. The frontend lets users select Jane/John roles, and review/signatory values come from request payloads.

Update: enforce organization membership and permissions server-side on all document, filing and administrative routes. Bind the review actor to the authenticated account; distinguish that actor from the legal signatory. Use durable audit events. Explicitly decide whether all users belong to one shared organization; do not assume isolation exists.

Acceptance: a user outside a filing's authorized organization cannot read or modify it; a preparer cannot become an administrator or authenticated reviewer through a dropdown or edited request.

### 5. High: validation and delivery are not a completed filing journey

Evidence: `service.py` deliberately requires an independent validator; `arelle_validator.py` expressly reports `filing_approval: False`; `submission.py` has `production_enabled: False`, no connected provider API and no direct transport. `package.py` creates an unconstrained ZIP; KVK's published iXBRL examples use `.xbri` packages. Format, manifest, dependencies and extension taxonomy requirements need route-specific qualification, not a filename-only change.

Update: qualify the independent validator against the applicable official conformance suite and representative positive/negative reports. Implement either an integrated delivery route or an explicit manual-provider checklist. Record transmitted package identity, processing result, rejection details and receipt. Show “Not submitted” persistently until supported by actual delivery evidence; distinguish a user-uploaded receipt from independently verified acceptance.

Acceptance: “Checks passed”, “Package downloaded”, “Sent” and “Accepted by KVK” are distinct states. Failed or unavailable checks never produce a green filing-ready status.

### 6. High: test coverage no longer exercises key API flows

Execution: `env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY app/.venv/bin/python -m pytest -q` produced **42 passed and 13 setup errors**. The shared fixture at `tests/test_regressions.py:172` still patches the removed `_DATA_DIR`; those 13 API tests never execute. `node tests/workspace.test.cjs` passed.

Update: adapt fixtures to the Supabase store and authentication boundary. Add isolated integration coverage for persistence failures, ownership, real reviewer identity, release-cache changes and a representative full preparation/export journey. Passing the remaining unit tests does not establish submission readiness.

## English-first experience

Some tag rendering already prefers `label_en` and search includes both languages (`workspace.js:736–778`). Preserve this. The gap is broader than translating four size names:

- `index.html` declares `lang="nl"` although most interface text is English. Set the document language to the selected interface language.
- Reporting profile options are filled from Dutch metadata names (`workspace.js:204–206`). Add reviewed English display names and retain the original Dutch names as secondary text.
- Use official taxonomy English labels where present. Where absent, use a reviewed glossary or clearly labelled translation; do not silently invent official labels. Keep concept QNames and schema references unchanged.
- Translate concept definitions, rule explanations, profile variants, errors, help and review/export instructions, not just navigation.
- Separate interface language, report language and number-entry format. An English interface should not silently reinterpret Dutch-formatted amounts.

Suggested display vocabulary (product wording, not a replacement for official legal terminology):

| Dutch / technical term | English display | Helpful explanation |
|---|---|---|
| Jaarrekening | Financial statements | The company's annual financial statements. |
| Jaarverantwoording | Annual reporting | The applicable annual reporting package. |
| Boekjaar | Financial year | The start and end dates covered by this report. |
| Klein / middelgroot / groot | Small / medium-sized / large | The applicable reporting size category; provide the official criteria. |
| Publicatiestukken | Financial statements for public filing | The version intended for publication; requirements depend on the profile. |
| Geconsolideerd / enkelvoudig | Consolidated / company-only | Group accounts versus the individual legal entity's accounts. |
| Vastgesteld / niet vastgesteld | Adopted / not yet adopted | Formal approval status of the financial statements. |
| Deponeren | File with KVK | Deliver the report through the applicable filing route. |
| Taxonomy / entry point | Reporting rules / reporting profile | The technical definitions selected for this filing. |
| QName / context | Technical tag identifier / period and scope | Keep technical identifiers in expandable details. |
| Sign-Off & Freeze | Review and lock this version | Explain who reviewed it and what changes would require renewed checks. |

For example: **“Small company — Dutch accounting standards”**, followed by **“Kleine rechtspersoon — NL-GAAP”**. Search should find either language.

## Recommended first-time user journey

1. **Start with what this service does.** Explain preparation, checking, delivery and current limitations. Offer a practice example and a short checklist of documents and decisions needed.
2. **Identify company and financial year.** Require confirmation of the KVK number and company name. Remove the hard-coded 2024 dates currently paired with NT21 2026. Do not infer a financial year merely from today's date.
3. **Choose the reporting profile through questions.** Ask accounting framework, company size, sector, group/company-only scope and filing purpose. Include “I'm not sure” guidance with official criteria or accountant review. Do not ask a beginner to select a raw taxonomy ID.
4. **Upload and inspect the financial statements.** Explain supported DOCX features. Show extracted content beside the source or a faithful preview, list unsupported images/layouts, and require review of omissions. The current renderer is intentionally basic.
5. **Review suggested tags.** Explain a tag as a link between an amount/disclosure and the reporting definition. Show English and Dutch names, a definition, exact source, current/prior year, currency and scale. Give explicit examples for `1.234,56` and `1,234.56`. Keep individual confirmation and do not equate matching with correctness.
6. **Fix issues.** Group blockers, warnings and informational messages. Each issue should say what happened, why it matters, where it occurs and how to fix it, with a direct link to the relevant field. Separate completeness, accounting consistency, technical validation and submission readiness.
7. **Review and lock.** Present a readable summary of company, dates, profile, adoption status, report version and unresolved issues. Record the real review actor. Explain the effect of reopening.
8. **Deliver and retain proof.** Show the supported route, required credentials/attachments and precise next action. A download is not a filing. Retain the final processing result and a receipt with package identity.

Use one primary next-step action, progress with meaningful completion criteria, contextual explanations for unavailable actions and an expert-details panel. Current first-load behaviour opens “Entity & Taxonomy” directly, while the ribbon exposes Diagnostics, Arelle, Provider handoff and Freeze at the same level. These choices should be introduced when relevant.

Keyboard/focus and responsive verification are still needed: the source includes fixed modal minimum widths, a dense ribbon and no responsive media rules in the reviewed stylesheet. Test keyboard-only operation, visible focus, labelled inputs, modal focus return, readable errors and normal laptop/zoom layouts.

## Delivery order and acceptance gate

1. Fix authentication, durable save, access control and taxonomy cache identity; restore API tests.
2. Qualify format-specific taxonomy releases, dependencies, report packaging and independent validation. Expose truthful readiness from startup.
3. Implement English-first terminology and the guided preparation/review workflow.
4. Complete the chosen delivery/receipt workflow and test it in the appropriate preproduction environment.
5. Run observed usability sessions with first-time filers using synthetic examples, including a wrong period, Dutch number formatting, missing disclosure, save failure and rejected submission.

A beginner should be able to explain which company/year is being filed, why the profile applies, whether their work is saved, which issues remain, and whether KVK has actually accepted the report. Those are better acceptance criteria than a visually complete dashboard.
