# Local code and Vercel deployment audit — 19 September 2026

## Conclusion

Not ready to certify as fully updated or working. Current local commit is `bebe164` (19 September). A read-only `git ls-remote` check confirmed GitHub `Orionka2024/DigiHub` HEAD and `main` both match the local revision exactly: `bebe164d3b1d7c4894c3e4105802120929d007a8`. The code findings therefore also apply to current GitHub main. The supplied deployment URL redirects unauthenticated requests to Vercel SSO. The supplied dashboard URL returns an HTML dashboard shell, but this did not provide authenticated access to the application, deployment source revision, environment configuration or runtime logs. Browser automation also failed during initialization. Local findings below are confirmed; whether this exact revision is deployed remains unverified.

## Findings

### P1 — Bundled taxonomy cannot load

`app/data/taxonomies/nt21_kvk.json:10` selects `taxonomy.zip`, but the manifest contains no `sha256`. `app/main.py:168` defaults the expected digest to an empty string; verification therefore rejects the archive. A fresh import under `VERCEL=1` returned `taxonomy_count: 0`, `errors: ["nt21_kvk.json: Package checksum mismatch."]`, and `export_ready: false`. This prevents the normal taxonomy selection/tagging workflow even before filing-validation restrictions apply.

The 44,844,349-byte local ZIP has SHA-256 `5d648d0185f31eb7f12dffc1e6771eeddb061ff59147e0dd50ebfe118dfda89e`. This is an observed file identity, not proof of official provenance. Verify archive origin, metadata and entry points before recording its checksum. It is a beta; do not mark it as an officially final release. The loader correctly overrides the manifest's misleading `final` status for this `.b` version.

### P1 — Filing state is not durable/shared on Vercel

`api/index.py:9` directs storage to `/tmp/kvk_data`. `app/store.py:173` keeps documents and snapshots in process-local dictionaries. Upload and subsequent create/map requests depend on reaching the same surviving process; explicit Save only writes local temporary JSON. Another instance, a restart or a new deployment can lose access to the document/filing, including saved work.

Use durable database/object storage and load state by identifier for every request, with atomic updates. Vercel describes `/tmp` as scratch space and recommends object storage for persistence: https://vercel.com/docs/functions/runtimes and https://vercel.com/kb/guide/how-can-i-use-files-in-serverless-functions .

### P1 — Login does not enforce filing ownership or administrator roles

`app/main.py:76` verifies that a user is logged in but discards the identity. Store keys and APIs have no user/organization ownership check. For example, `/api/workspace/load/{kvk_number}` (`app/main.py:899`) loads by company number without checking the requesting user. Administrator endpoints receive the same login-only protection. A synthetic non-admin account could read the admin taxonomy endpoint locally (HTTP 200).

If all users are intentionally one trusted team this needs an explicit access policy; it is not safe isolation for separate customers. Add ownership/team authorization and server-enforced administrative roles. Reviewer names still come from editable UI fields rather than being bound to the authenticated identity.

### P1, conditional on configuration — Authentication accepts a public fallback signing key

`app/auth.py:12` uses a hard-coded development JWT key when the environment variable is missing. A production deployment should fail startup instead. Live secret configuration was not accessible, so exploitation of the supplied deployment is not established. The synthetic login test also confirmed the cookie omits `Secure` (`app/auth.py:93`); enable it in HTTPS deployments. Authentication tokens were neither printed nor tested against the live deployment.

### P2 — Arelle is absent from deployment dependencies; versions are unpinned

The root `requirements.txt`, used with the root Vercel Python build, contains neither `arelle-release` nor a reference to `app/requirements-validator.txt`. Installing Arelle in a developer's virtual environment does not install it on Vercel. The root dependencies are unpinned, unlike the local app dependency list, so deploy and local test versions can differ. Include and qualify the intended validator dependencies and pin a tested deployment set. The adapter still deliberately does not certify 2026 filing suitability.

### P2 — Current regression suite no longer passes

`app/.venv/bin/python -m pytest -q`: **45 passed, 10 failed**, two dependency deprecation warnings. All ten observed failures received HTTP 401 at the newly added authentication middleware. The API fixtures (`tests/test_regressions.py:167`) never log in. These are test integration failures, not evidence that legitimate logins fail. They also mean the existing suite currently stops before exercising the protected mapping/save/freeze flows.

Update fixtures to authenticate through a test account, and add tests for unauthenticated rejection, ownership and roles. Imports in the fixtures still mix `KVK_v2.app.*` with `app.*`; normalize them to avoid testing a different module/store instance.

### P2 — Taxonomy parsing lifecycle needs serverless qualification

`app/main.py:215` starts a daemon parsing thread outside a request lifecycle, using in-memory queue/status state. This is a local-process design; it is not a durable background job on Vercel. After the checksum issue is fixed, test cold starts, instance changes and selected-entry-point loading. Prefer prebuilt validated taxonomy indexes or durable background jobs over relying on an idle function process continuing work.

## What passed

- JavaScript regression checks (`node tests/workspace.test.cjs`).
- JavaScript syntax checks for workspace and login code.
- Local synthetic-account smoke checks: unauthenticated `/` redirects (307), unauthenticated API returns 401, login returns 200, authenticated root/API return 200, logout returns 200, API after logout returns 401.
- Local source contains the guided tagging changes: profile selection, filtered Tagging review, document/table suggestions, and confirm/edit/skip flow.
- Fresh application import succeeds, but reports the taxonomy-loading failure above. `/health` reports `status: ok` even when taxonomy loading fails; use readiness fields rather than that string as a release gate.

## Live checks and limits

The deployment root returned HTTP 302 to Vercel SSO. The dashboard HTML was reachable but did not establish access to the running app. No live login, document upload, tagging, save/load, source-asset comparison, validator execution or submission was verified. No financial data was uploaded and no filing was transmitted. No credentials or tokens were requested or exposed.

The earlier 55-pass result described an earlier revision; it is superseded by the current 45-pass/10-fail result. Do not rely on the earlier readiness statement for this Vercel build.

## Order of repair

1. Verify/fix the taxonomy manifest and confirm usable selected-entry-point loading.
2. Implement durable shared storage and per-user/team authorization.
3. Require a production JWT secret and secure cookies; pin deployment dependencies, including the diagnostic validator if offered in the UI.
4. Update authenticated regression tests and test cold starts and multi-instance workflows.
5. Obtain authenticated access to the exact deployment, verify its source revision and run end-to-end preparation tests using a synthetic document.

Official filing remains a separate release gate requiring the applicable final taxonomy/rules and qualified provider/direct transport. This audit made no application changes or deployments. An existing deleted spreadsheet in the working tree was left untouched.

## Production alias verification — subsequent check

The user supplied https://digi-hub-xi.vercel.app/ after the initial audit. This alias is publicly reachable and supersedes the earlier live-access limitation for unauthenticated checks:

- `/`: HTTP 307 to the application's `/login.html`, not Vercel SSO.
- `/login.html`: HTTP 200; exact byte match with the audited local file.
- `/workspace.js`: HTTP 200; exact byte match with the audited local file (SHA-256 `5c5024f9fbaa901986f3f1bd5108d3e423c7e7d2a7997e1d0d1a768d749cad8e`).
- `/api/taxonomy/list`: HTTP 401 without application credentials, as expected.
- `/health`: HTTP 200, but `taxonomy_count: 0`, `taxonomy_ready: false`, `export_ready: false`, and `errors: ["nt21_kvk.json: Package checksum mismatch."]`.

The taxonomy blocker is therefore confirmed on the live production alias, not just reproduced locally. The checked frontend files are current. These asset matches do not independently identify every deployed backend file or its source commit. Authenticated upload/tag/save/load and validator workflows remain untested; no credentials were supplied and no submissions were made. The live application must not be reported as fully working merely because its health endpoint returns HTTP 200 or `status: ok`.
