"""Reporting profiles and combination gating for Dutch KVK annual accounts.

Phase 1 implementation:
- Defines supported reporting profiles across financial year, NL-GAAP/IFRS, company size,
  sector and standalone/consolidated scope.
- Explicitly blocks unsupported or illegal combinations under Dutch law (BW2 Title 9) and SBR rules.
- Pins taxonomy and rule versions per profile.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Literal

RULES_2025 = "KVK-RM-2025-10-31-errata-2026-02-12"

FrameworkType = Literal["nlgaap", "ifrs"]
CompanySizeType = Literal["micro", "klein", "middelgroot", "groot"]
SectorType = Literal["general", "bank", "insurer", "investment", "pension", "housing", "healthcare", "nonprofit"]
ScopeType = Literal["standalone", "consolidated", "both"]


class UnsupportedProfileError(ValueError):
    """Raised when an invalid or unsupported reporting profile combination is requested."""
    def __init__(self, code: str, message: str, reason: str = ""):
        full_msg = f"[{code}] {message}" + (f" (Reason: {reason})" if reason else "")
        super().__init__(full_msg)
        self.code = code
        self.message = message
        self.reason = reason


@dataclass(frozen=True)
class ReportingProfile:
    id: str
    name: str
    name_en: str
    name_nl: str
    financial_year: int
    framework: FrameworkType
    company_size: CompanySizeType
    sector: SectorType
    scope: ScopeType
    legal_basis: str
    taxonomy_id: str
    taxonomy_version: str
    rules_version: str
    entry_point_key: str
    qualification: str = "candidate"  # "candidate" | "qualified" | "not_qualified"
    is_production_supported: bool = True
    description_en: str = ""
    description_nl: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["profile_id"] = self.id
        return data


# ---------------------------------------------------------------------------
# Supported 2025 Profile Catalog
# ---------------------------------------------------------------------------

_PROFILES: dict[str, ReportingProfile] = {
    "2025-nlgaap-micro-general-standalone": ReportingProfile(
        id="2025-nlgaap-micro-general-standalone",
        name="Micro company — NL-GAAP (Standalone)",
        name_en="Micro company — NL-GAAP (Standalone)",
        name_nl="Micro-onderneming — NL-GAAP (Enkelvoudig)",
        financial_year=2025,
        framework="nlgaap",
        company_size="micro",
        sector="general",
        scope="standalone",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:395a BW (Micro regime)",
        taxonomy_id="KVK_IXBRL_2025",
        taxonomy_version="2025-12-31",
        rules_version=RULES_2025,
        entry_point_key="nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Abbreviated balance sheet and minimal explanatory notes for micro companies.",
        description_nl="Verkorte balans en minimale toelichting voor micro-ondernemingen."
    ),
    "2025-nlgaap-klein-general-standalone": ReportingProfile(
        id="2025-nlgaap-klein-general-standalone",
        name="Small company — NL-GAAP (Standalone)",
        name_en="Small company — NL-GAAP (Standalone)",
        name_nl="Kleine rechtspersoon — NL-GAAP (Enkelvoudig)",
        financial_year=2025,
        framework="nlgaap",
        company_size="klein",
        sector="general",
        scope="standalone",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:396 BW (Small company regime)",
        taxonomy_id="KVK_IXBRL_2025",
        taxonomy_version="2025-12-31",
        rules_version=RULES_2025,
        entry_point_key="nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Condensed balance sheet and notes under Title 9 Book 2 Dutch Civil Code.",
        description_nl="Verkorte balans en toelichting conform Titel 9 Boek 2 BW."
    ),
    "2025-nlgaap-middelgroot-general-standalone": ReportingProfile(
        id="2025-nlgaap-middelgroot-general-standalone",
        name="Medium-sized company — NL-GAAP (Standalone)",
        name_en="Medium-sized company — NL-GAAP (Standalone)",
        name_nl="Middelgrote rechtspersoon — NL-GAAP (Enkelvoudig)",
        financial_year=2025,
        framework="nlgaap",
        company_size="middelgroot",
        sector="general",
        scope="standalone",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:397 BW",
        taxonomy_id="KVK_IXBRL_2025",
        taxonomy_version="2025-12-31",
        rules_version=RULES_2025,
        entry_point_key="nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Balance sheet, simplified profit and loss account, notes and management report.",
        description_nl="Balans, vereenvoudigde winst-en-verliesrekening, toelichting en bestuursverslag."
    ),
    "2025-nlgaap-middelgroot-general-consolidated": ReportingProfile(
        id="2025-nlgaap-middelgroot-general-consolidated",
        name="Medium-sized company — NL-GAAP (Consolidated)",
        name_en="Medium-sized company — NL-GAAP (Consolidated)",
        name_nl="Middelgrote rechtspersoon — NL-GAAP (Geconsolideerd)",
        financial_year=2025,
        framework="nlgaap",
        company_size="middelgroot",
        sector="general",
        scope="consolidated",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:406 BW",
        taxonomy_id="KVK_IXBRL_2025",
        taxonomy_version="2025-12-31",
        rules_version=RULES_2025,
        entry_point_key="nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Consolidated annual report for medium-sized group entities.",
        description_nl="Geconsolideerde jaarrekening voor middelgrote groepsentiteiten."
    ),
    "2025-nlgaap-groot-general-standalone": ReportingProfile(
        id="2025-nlgaap-groot-general-standalone",
        name="Large company — NL-GAAP (Standalone)",
        name_en="Large company — NL-GAAP (Standalone)",
        name_nl="Grote rechtspersoon — NL-GAAP (Enkelvoudig)",
        financial_year=2025,
        framework="nlgaap",
        company_size="groot",
        sector="general",
        scope="standalone",
        legal_basis="Burgerlijk Wetboek Boek 2 Titel 9",
        taxonomy_id="KVK_IXBRL_2025",
        taxonomy_version="2025-12-31",
        rules_version=RULES_2025,
        entry_point_key="nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Full statutory financial statements under Dutch GAAP.",
        description_nl="Volledige jaarrekening conform NL-GAAP."
    ),
    "2025-nlgaap-groot-general-consolidated": ReportingProfile(
        id="2025-nlgaap-groot-general-consolidated",
        name="Large company — NL-GAAP (Consolidated)",
        name_en="Large company — NL-GAAP (Consolidated)",
        name_nl="Grote rechtspersoon — NL-GAAP (Geconsolideerd)",
        financial_year=2025,
        framework="nlgaap",
        company_size="groot",
        sector="general",
        scope="consolidated",
        legal_basis="Burgerlijk Wetboek Boek 2 Titel 9 & Art. 2:406 BW",
        taxonomy_id="KVK_IXBRL_2025",
        taxonomy_version="2025-12-31",
        rules_version=RULES_2025,
        entry_point_key="nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Full consolidated financial statements under Dutch GAAP for large groups.",
        description_nl="Volledige geconsolideerde jaarrekening onder NL-GAAP voor grote groepen."
    ),
    "2025-ifrs-groot-general-consolidated": ReportingProfile(
        id="2025-ifrs-groot-general-consolidated",
        name="Large company — EU-IFRS (Consolidated)",
        name_en="Large company — EU-IFRS (Consolidated)",
        name_nl="Grote rechtspersoon — EU-IFRS (Geconsolideerd)",
        financial_year=2025,
        framework="ifrs",
        company_size="groot",
        sector="general",
        scope="consolidated",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:362 lid 8 / IAS Regulation (EC) 1606/2002",
        taxonomy_id="KVK_IXBRL_2025",
        taxonomy_version="2025-12-31",
        rules_version=RULES_2025,
        entry_point_key="ifrs",
        qualification="candidate",
        is_production_supported=True,
        description_en="EU-endorsed IFRS consolidated statements with Title 9 Part 9 disclosures.",
        description_nl="Geconsolideerde jaarrekening conform door de EU goedgekeurde IFRS."
    ),

    # ---------------------------------------------------------------------------
    # Supported 2026 Profile Catalog (NT21)
    # ---------------------------------------------------------------------------
    "2026-nlgaap-micro-general-standalone": ReportingProfile(
        id="2026-nlgaap-micro-general-standalone",
        name="Micro company — NL-GAAP (Standalone)",
        name_en="Micro company — NL-GAAP (Standalone)",
        name_nl="Micro-onderneming — NL-GAAP (Enkelvoudig)",
        financial_year=2026,
        framework="nlgaap",
        company_size="micro",
        sector="general",
        scope="standalone",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:395a BW (Micro regime)",
        taxonomy_id="NT21_KVK_20261209_b",
        taxonomy_version="20261209.b",
        rules_version="NT21-KVK-2026-08-13-v1_1",
        entry_point_key="micro_nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Abbreviated balance sheet and minimal explanatory notes for micro companies (NT21).",
        description_nl="Verkorte balans en minimale toelichting voor micro-ondernemingen (NT21)."
    ),
    "2026-nlgaap-klein-general-standalone": ReportingProfile(
        id="2026-nlgaap-klein-general-standalone",
        name="Small company — NL-GAAP (Standalone)",
        name_en="Small company — NL-GAAP (Standalone)",
        name_nl="Kleine rechtspersoon — NL-GAAP (Enkelvoudig)",
        financial_year=2026,
        framework="nlgaap",
        company_size="klein",
        sector="general",
        scope="standalone",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:396 BW (Small company regime)",
        taxonomy_id="NT21_KVK_20261209_b",
        taxonomy_version="20261209.b",
        rules_version="NT21-KVK-2026-08-13-v1_1",
        entry_point_key="klein_nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Condensed balance sheet and notes under Title 9 Book 2 Dutch Civil Code (NT21).",
        description_nl="Verkorte balans en toelichting conform Titel 9 Boek 2 BW (NT21)."
    ),
    "2026-nlgaap-middelgroot-general-standalone": ReportingProfile(
        id="2026-nlgaap-middelgroot-general-standalone",
        name="Medium-sized company — NL-GAAP (Standalone)",
        name_en="Medium-sized company — NL-GAAP (Standalone)",
        name_nl="Middelgrote rechtspersoon — NL-GAAP (Enkelvoudig)",
        financial_year=2026,
        framework="nlgaap",
        company_size="middelgroot",
        sector="general",
        scope="standalone",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:397 BW",
        taxonomy_id="NT21_KVK_20261209_b",
        taxonomy_version="20261209.b",
        rules_version="NT21-KVK-2026-08-13-v1_1",
        entry_point_key="middelgroot_nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Balance sheet, simplified profit and loss account, notes and management report (NT21).",
        description_nl="Balans, vereenvoudigde winst-en-verliesrekening, toelichting en bestuursverslag (NT21)."
    ),
    "2026-nlgaap-middelgroot-general-consolidated": ReportingProfile(
        id="2026-nlgaap-middelgroot-general-consolidated",
        name="Medium-sized company — NL-GAAP (Consolidated)",
        name_en="Medium-sized company — NL-GAAP (Consolidated)",
        name_nl="Middelgrote rechtspersoon — NL-GAAP (Geconsolideerd)",
        financial_year=2026,
        framework="nlgaap",
        company_size="middelgroot",
        sector="general",
        scope="consolidated",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:406 BW",
        taxonomy_id="NT21_KVK_20261209_b",
        taxonomy_version="20261209.b",
        rules_version="NT21-KVK-2026-08-13-v1_1",
        entry_point_key="middelgroot_nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Consolidated annual report for medium-sized group entities (NT21).",
        description_nl="Geconsolideerde jaarrekening voor middelgrote groepsentiteiten (NT21)."
    ),
    "2026-nlgaap-groot-general-standalone": ReportingProfile(
        id="2026-nlgaap-groot-general-standalone",
        name="Large company — NL-GAAP (Standalone)",
        name_en="Large company — NL-GAAP (Standalone)",
        name_nl="Grote rechtspersoon — NL-GAAP (Enkelvoudig)",
        financial_year=2026,
        framework="nlgaap",
        company_size="groot",
        sector="general",
        scope="standalone",
        legal_basis="Burgerlijk Wetboek Boek 2 Titel 9",
        taxonomy_id="NT21_KVK_20261209_b",
        taxonomy_version="20261209.b",
        rules_version="NT21-KVK-2026-08-13-v1_1",
        entry_point_key="groot_nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Full statutory financial statements under Dutch GAAP (NT21).",
        description_nl="Volledige jaarrekening conform NL-GAAP (NT21)."
    ),
    "2026-nlgaap-groot-general-consolidated": ReportingProfile(
        id="2026-nlgaap-groot-general-consolidated",
        name="Large company — NL-GAAP (Consolidated)",
        name_en="Large company — NL-GAAP (Consolidated)",
        name_nl="Grote rechtspersoon — NL-GAAP (Geconsolideerd)",
        financial_year=2026,
        framework="nlgaap",
        company_size="groot",
        sector="general",
        scope="consolidated",
        legal_basis="Burgerlijk Wetboek Boek 2 Titel 9 & Art. 2:406 BW",
        taxonomy_id="NT21_KVK_20261209_b",
        taxonomy_version="20261209.b",
        rules_version="NT21-KVK-2026-08-13-v1_1",
        entry_point_key="groot_nlgaap",
        qualification="candidate",
        is_production_supported=True,
        description_en="Full consolidated financial statements under Dutch GAAP for large groups (NT21).",
        description_nl="Volledige geconsolideerde jaarrekening onder NL-GAAP voor grote groepen (NT21)."
    ),
    "2026-ifrs-groot-general-consolidated": ReportingProfile(
        id="2026-ifrs-groot-general-consolidated",
        name="Large company — EU-IFRS (Consolidated)",
        name_en="Large company — EU-IFRS (Consolidated)",
        name_nl="Grote rechtspersoon — EU-IFRS (Geconsolideerd)",
        financial_year=2026,
        framework="ifrs",
        company_size="groot",
        sector="general",
        scope="consolidated",
        legal_basis="Burgerlijk Wetboek Boek 2, Art. 2:362 lid 8 / IAS Regulation (EC) 1606/2002",
        taxonomy_id="NT21_KVK_20261209_b",
        taxonomy_version="20261209.b",
        rules_version="NT21-KVK-2026-08-13-v1_1",
        entry_point_key="ifrs",
        qualification="candidate",
        is_production_supported=True,
        description_en="EU-endorsed IFRS consolidated statements with Title 9 Part 9 disclosures (NT21).",
        description_nl="Geconsolideerde jaarrekening conform door de EU goedgekeurde IFRS (NT21)."
    ),
}


def get_profile(profile_id: str) -> ReportingProfile:
    """Retrieve a supported profile or raise UnsupportedProfileError."""
    # Enforce profile policy and rejection of unsupported years / combinations
    match = re.match(r"^(\d{4})-([a-z]+)-([a-z]+)-([a-z]+)-([a-z]+)$", profile_id.lower().strip())
    if match:
        year_str, framework, size, sector, scope = match.groups()
        year = int(year_str)
        if year not in (2025, 2026):
            raise ValueError(f"Unsupported profile: reporting year {year} is not in the supported scope.")
        if size == "micro" and framework == "ifrs":
            raise ValueError("Unsupported profile: Micro companies cannot report under IFRS.")
        if size == "micro" and scope in ("consolidated", "both"):
            raise ValueError("Unsupported profile: Micro companies cannot file consolidated financial statements.")
        if size == "klein" and framework == "ifrs":
            raise ValueError("Unsupported profile: Small companies cannot file full EU-IFRS.")
        if scope in ("consolidated", "both") and size not in ("middelgroot", "groot"):
            raise ValueError(f"Unsupported profile: Consolidation not permitted for size '{size}'.")

    if profile_id not in _PROFILES:
        raise ValueError(f"Unsupported profile '{profile_id}'.")
    return _PROFILES[profile_id]


def check_profile(snapshot, taxonomy) -> None:
    """Validate that snapshot parameters conform to its declared reporting profile."""
    if not getattr(snapshot, "profile_id", None):
        return
    profile = get_profile(snapshot.profile_id)

    # 1. Period check: period_end must match profile's financial year
    if snapshot.period_end.year != profile.financial_year and snapshot.period_start.year != profile.financial_year:
        raise ValueError(
            f"Filing period {snapshot.period_start} to {snapshot.period_end} does not match profile financial year {profile.financial_year}."
        )

    # 2. Taxonomy year check
    tax_year = getattr(taxonomy, "reporting_year", 0)
    if tax_year and tax_year != profile.financial_year:
        raise ValueError(
            f"Taxonomy reporting year {tax_year} does not match profile financial year {profile.financial_year}."
        )

    # 3. Entry point check
    ep = snapshot.entry_point_key.lower()
    if profile.framework == "nlgaap" and "ifrs" in ep:
        raise ValueError(f"Profile framework '{profile.framework}' incompatible with IFRS entry point '{snapshot.entry_point_key}'.")
    if profile.framework == "ifrs" and "nlgaap" in ep:
        raise ValueError(f"Profile framework '{profile.framework}' incompatible with NL-GAAP entry point '{snapshot.entry_point_key}'.")


def catalog() -> list[dict]:
    """Return all supported candidate profiles."""
    return [p.to_dict() for p in _PROFILES.values()]


# Aliases for backward/forward compatibility
get_profile_by_id = get_profile
list_supported_profiles = lambda include_beta=True: list(_PROFILES.values())
validate_profile_parameters = lambda y, f, s, sec="general", sc="standalone": get_profile(f"{y}-{f}-{s}-{sec}-{sc}")
