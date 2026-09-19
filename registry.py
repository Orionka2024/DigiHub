"""Taxonomy registry — stores and serves verified NT taxonomy releases.

The registry enforces:
  * Only officially-final taxonomy packages can be registered.
  * Verified packages must carry a SHA-256 checksum.
  * Unverified directories may be registered separately for preparation only.
  * Taxonomy IDs must be unique.

Two classes are provided:
  TaxonomyRelease     — lightweight release record (for backward compatibility)
  EnrichedTaxonomyRelease — full-featured release with parsed concepts + rules
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from taxonomy.concept import ConceptMetadata
    from taxonomy.rules import RulesEngine, ValidationRule, ChecklistSection
    from models import FilingSnapshot


@dataclass(frozen=True)
class TaggingRequirement:
    """One signed-off requirement imported from the applicable KVK taxonomy/RTS.

    Conditional requirements cannot be silently ignored: the reviewer must mark
    them as applicable (and provide a fact) or explicitly not applicable.
    """
    id: str
    qname: str | None
    section: str | None
    conditional: bool = False


@dataclass(frozen=True)
class EntryPointMeta:
    """Metadata about one entry point from the taxonomy manifest."""
    key: str
    file: str
    name: str
    company_class: str   # micro / klein / middelgroot / groot
    framework: str       # nlgaap / ifrs
    sector: str          # general / bank / insurer / investment / pension / ...
    consolidation: str   # both / consolidated / separate
    domain: str          # kvk / jenv / rj / ...


@dataclass(frozen=True)
class TaxonomyRelease:
    """Lightweight taxonomy release — backward-compatible with the original API."""
    id: str
    status: str
    entry_points: dict[str, str]         # key → file path (legacy flat format)
    namespaces: dict[str, str]           # prefix → URI
    sha256: str
    requirements: dict[str, tuple[TaggingRequirement, ...]]  # ep_key → requirements
    package_verified: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.requirements, tuple):
            object.__setattr__(self, "requirements", {key: self.requirements for key in self.entry_points})

    def entry_point(self, key: str) -> str:
        if self.status != "final":
            raise ValueError(f"Taxonomy release {self.id} is not final.")
        try:
            return self.entry_points[key]
        except KeyError as error:
            raise ValueError(f"Unknown entry point {key!r} for {self.id}.") from error


@dataclass
class EnrichedTaxonomyRelease:
    """Full-featured taxonomy release with parsed concepts, rules and metadata.

    This is the preferred class for new code.  Legacy endpoints that expect
    a TaxonomyRelease can call .to_legacy() to obtain a compatible object.
    """
    id: str
    status: str
    version: str              # e.g. "20261209.b"
    name: str
    authority: str            # e.g. "KVK / SBR Programma"
    publication_date: str
    reporting_year: int
    reporting_date: str       # "YYYY-MM-DD"
    sha256: str
    package_verified: bool = False
    package_path: str = ""   # absolute path to the package dir/zip
    entity_scheme: str = "http://www.kvk.nl/kvk-id"
    currency: str = "EUR"

    # Entry point metadata keyed by ep_key
    entry_point_meta: dict[str, EntryPointMeta] = field(default_factory=dict)

    # Legacy flat entry_points map (ep_key → file path), kept for backward compat
    entry_points: dict[str, str] = field(default_factory=dict)

    # All namespaces
    namespaces: dict[str, str] = field(default_factory=dict)

    # Concept metadata (qname → ConceptMetadata) — populated by importer
    concepts: dict[str, "ConceptMetadata"] = field(default_factory=dict)

    # Parsed validation rules (rule_id → ValidationRule)
    validation_rules: dict[str, "ValidationRule"] = field(default_factory=dict)

    # Rules engine instance
    rules_engine: "RulesEngine | None" = None

    # Legacy requirements map (ep_key → tuple[TaggingRequirement])
    requirements: dict[str, tuple[TaggingRequirement, ...]] = field(default_factory=dict)

    # Taxonomy files discovered during parsing
    taxonomy_files: list[str] = field(default_factory=list)
    complete_entry_points: set[str] = field(default_factory=set)

    def entry_point(self, key: str) -> str:
        if self.status != "final":
            raise ValueError(f"Taxonomy release {self.id} is not final.")
        if key not in self.entry_points:
            raise ValueError(f"Unknown entry point {key!r} for {self.id}.")
        return self.entry_points[key]

    def get_concepts_for_ep(
        self, ep_key: str, *, exclude_abstract: bool = True
    ) -> list["ConceptMetadata"]:
        """Return concepts applicable to a given entry point."""
        return [
            c for c in self.concepts.values()
            if ep_key in c.entry_points
            and (not exclude_abstract or not c.abstract)
        ]

    def get_concept(self, qname: str) -> "ConceptMetadata | None":
        return self.concepts.get(qname)

    def build_checklist(
        self,
        ep_key: str,
        snapshot: "FilingSnapshot | None" = None,
    ) -> list["ChecklistSection"]:
        """Build the dynamic mandatory checklist for a given entry-point profile."""
        if self.rules_engine is None:
            return []
        concepts = self.get_concepts_for_ep(ep_key, exclude_abstract=True)
        return self.rules_engine.build_checklist(concepts, ep_key, snapshot)

    def to_legacy(self) -> TaxonomyRelease:
        """Convert to legacy TaxonomyRelease for backward-compatible code paths."""
        return TaxonomyRelease(
            id=self.id,
            status=self.status,
            entry_points=self.entry_points,
            namespaces=self.namespaces,
            sha256=self.sha256,
            requirements=self.requirements,
            package_verified=self.package_verified,
        )

    def __post_init__(self) -> None:
        self.entry_point_meta = {
            key: EntryPointMeta(key=key, **{k: value.get(k, "") for k in
                ("file", "name", "company_class", "framework", "sector", "consolidation", "domain")})
            if isinstance(value, dict) else value for key, value in self.entry_point_meta.items()
        }

    def select_entry_point(
        self,
        company_class: str = "groot",
        sector: str = "general",
        framework: str = "nlgaap",
        consolidated: bool = True,
    ) -> str | None:
        """Return the best-matching entry point key for a filing profile.

        Requires exact company class, sector, framework and consolidation support.
        Returns None if no entry points are registered.
        """
        candidates = list(self.entry_point_meta.values())
        if not candidates:
            return None

        mode = "consolidated" if consolidated else "separate"
        matches = [ep for ep in candidates if ep.company_class == company_class
                   and ep.sector == sector and ep.framework == framework
                   and ep.consolidation in ("both", mode)]
        if not matches:
            raise ValueError("No entry point matches the requested reporting profile.")
        return matches[0].key



class TaxonomyRegistry:
    """Thread-safe in-process taxonomy registry.

    Supports both TaxonomyRelease (legacy) and EnrichedTaxonomyRelease.
    """

    def __init__(self) -> None:
        # id → release (either type)
        self._releases: dict[str, TaxonomyRelease | EnrichedTaxonomyRelease] = {}

    def register(self, release: TaxonomyRelease | EnrichedTaxonomyRelease) -> None:
        if release.id in self._releases:
            raise ValueError(f"Taxonomy {release.id} already registered.")
        valid_sha = isinstance(release.sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", release.sha256)
        if not valid_sha:
            raise ValueError("Taxonomy package SHA-256 is required (64 hex chars).")
        if release.status != "final":
            raise ValueError("Only an officially final taxonomy release can be registered.")
        if not release.package_verified:
            raise ValueError("Taxonomy package has not been checksum-verified locally.")
        self._releases[release.id] = release

    def register_preview(self, release) -> None:
        """Expose a local package for preparation only; it cannot authorize export."""
        if release.package_verified:
            raise ValueError("Verified releases must use register().")
        if release.id in self._releases:
            raise ValueError(f"Taxonomy {release.id} already registered.")
        self._releases[release.id] = release

    def get(
        self, taxonomy_id: str
    ) -> TaxonomyRelease | EnrichedTaxonomyRelease:
        try:
            return self._releases[taxonomy_id]
        except KeyError as error:
            raise ValueError(f"Taxonomy {taxonomy_id!r} is not registered.") from error

    def get_enriched(
        self, taxonomy_id: str
    ) -> EnrichedTaxonomyRelease:
        rel = self.get(taxonomy_id)
        if isinstance(rel, EnrichedTaxonomyRelease):
            return rel
        raise ValueError(
            f"Taxonomy {taxonomy_id!r} is registered as a legacy TaxonomyRelease, "
            "not an EnrichedTaxonomyRelease. Re-install using the taxonomy importer."
        )

    def list_ids(self) -> list[str]:
        return list(self._releases.keys())

    def list_all(self) -> list[TaxonomyRelease | EnrichedTaxonomyRelease]:
        return list(self._releases.values())

    def activate(self, taxonomy_id: str) -> None:
        """Mark a taxonomy as the active version (for multi-version support)."""
        self.get(taxonomy_id)  # raises if not found
        # Store as a metadata attribute on the release
        rel = self._releases[taxonomy_id]
        object.__setattr__(rel, "_active", True) if hasattr(rel, "__dict__") else None

    def deactivate(self, taxonomy_id: str) -> None:
        self.get(taxonomy_id)
        rel = self._releases[taxonomy_id]
        object.__setattr__(rel, "_active", False) if hasattr(rel, "__dict__") else None

    def is_active(self, taxonomy_id: str) -> bool:
        rel = self._releases.get(taxonomy_id)
        if rel is None:
            return False
        return getattr(rel, "_active", True)  # default: active
