# Taxonomy qualification register

Checked against official SBR publications on 25 October 2026. This register is not an activation mechanism.

| Release | Format / purpose | Current qualification |
|---|---|---|
| NT21_KVK_20261209.b | Predefined NT21 profiles, reporting year 2026 | Bundled beta; preparation only. Not qualified for this application's iXBRL filing route. |
| NTiXBRL_KVK_20261231.a | Separate 2026 iXBRL family | Announced 22 October; candidate for development assessment only. Not installed or activated. |
| KVK iXBRL 2025, version 31 December 2025 | Supported-year candidate for production qualification | Official final packages/examples exist; not installed or qualified in this application. |

Sources: [2026 alpha announcement](https://www.sbr-nl.nl/alfaversie-van-ntixbrlkvk20261231-gepubliceerd), [2026 packages](https://www.sbr-nl.nl/sbr-domeinen/handelsregister/documentatie-boekjaar-2026), [2025 packages and conformance suite](https://www.sbr-nl.nl/sbr-domeinen/handelsregister/documentatie-boekjaar-2025-kvk), [release calendar](https://www.sbr-nl.nl/werken-met-sbr/taxonomie/releasekalender).

Before activating any final release, record and independently review:

1. Official download URL, original archive checksum, internal package identity, publication date and actual production availability (not just a scheduled date).
2. Filing format, supported financial-year policy, framework, sector, standalone/consolidated scope and applicable entry points.
3. All applicable dependency packages and checksums; complete offline DTS resolution.
4. Applicable RTS, Reporting Manual, errata and filing-rule versions.
5. Positive and negative official conformance tests, representative generated reports and provider preproduction acceptance.
6. Package type, extension taxonomy requirements, attachment requirements, file naming and final package-size limits.
7. Changed/deprecated concepts and a migration report for any existing draft. Do not replace a filing's pinned taxonomy silently.

The app enforces a conservative 50 MiB output-package cap as a product limit. The announcement describes a forthcoming change from 100 MB to 50 MB; the final applicable requirements and byte convention must still be verified with the provider. A compliant ZIP structure alone does not establish acceptance. Actual delivery remains disconnected; no status is inferred from a download.
