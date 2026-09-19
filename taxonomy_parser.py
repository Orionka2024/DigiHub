"""Taxonomy parser — reads the official NT21 taxonomy package.

The parser follows every linkbaseRef in every entry-point XSD,
resolving local file paths via the catalog.xml, and extracts:

1.  ConceptMetadata from XSD element declarations
2.  Label linkbases (NL + EN) → label_nl / label_en / documentation
3.  Presentation linkbases → parent/child hierarchy + link roles
4.  Calculation linkbases → CalcRelationship list
5.  Definition linkbases → DimensionRelationship / hypercube info
6.  Formula linkbases (ea:existenceAssertion, va:valueAssertion)
    → ValidationRule + MandatoryStatus

KEY DESIGN PRINCIPLE:
  A concept's mandatory status is derived from ea:existenceAssertion
  elements in the formula linkbase files (*-for.xml).
  Concepts not covered by an existenceAssertion are OPTIONAL.
  We never set mandatory=True simply because a concept exists in the XSD.

Conditional detection:
  An existenceAssertion is CONDITIONAL when it is wrapped in a gen:arc
  that connects it to a boolean filter (bf:andFilter / bf:orFilter) whose
  child filters depend on other concepts.  In practice the NT21 taxonomy
  uses a single unconditional existenceAssertion per mandatory concept.
  Where a boolean parent filter is detected we mark status=CONDITIONAL
  and record the filter structure as the condition description.
"""
from __future__ import annotations

import os
import urllib.parse
from pathlib import Path
from typing import Any
from lxml import etree as ET
from hashlib import sha256

from KVK_v2.taxonomy.concept import (
    CalcRelationship,
    ConceptMetadata,
    DimensionRelationship,
    PresentationRelationship,
    Reference,
)
from KVK_v2.taxonomy.rules import MandatoryStatus, RuleType, ValidationRule
from KVK_v2.registry import TaggingRequirement

# ---------------------------------------------------------------------------
# XML namespace constants
# ---------------------------------------------------------------------------
NS = {
    "xsd":      "http://www.w3.org/2001/XMLSchema",
    "link":     "http://www.xbrl.org/2003/linkbase",
    "xlink":    "http://www.w3.org/1999/xlink",
    "label":    "http://www.xbrl.org/2003/linkbase",
    "xbrli":    "http://www.xbrl.org/2003/instance",
    "ea":       "http://xbrl.org/2008/assertion/existence",
    "va":       "http://xbrl.org/2008/assertion/value",
    "cf":       "http://xbrl.org/2008/filter/concept",
    "variable": "http://xbrl.org/2008/variable",
    "gen":      "http://xbrl.org/2008/generic",
    "bf":       "http://xbrl.org/2008/filter/boolean",
    "msg":      "http://xbrl.org/2010/message",
    "cat":      "urn:oasis:names:tc:entity:xmlns:xml:catalog",
}

_LABEL_ROLE_VERBOSE = "http://www.xbrl.org/2003/role/verboseLabel"
_LABEL_ROLE_STANDARD = "http://www.xbrl.org/2003/role/label"
_LABEL_ROLE_DOC = "http://www.xbrl.org/2003/role/documentation"

_TAG = {k: "{" + v + "}" for k, v in NS.items()}


class CatalogResolver:
    """Resolves http:// taxonomy URIs to local filesystem paths via catalog.xml."""

    def __init__(self, catalog_path: Path | None) -> None:
        self.rules: list[tuple[str, str]] = []   # (uriStartString, rewritePrefix)
        self.base_dir: Path | None = catalog_path.parent if catalog_path else None
        if catalog_path and catalog_path.exists():
            self._parse(catalog_path)

    def _parse(self, path: Path) -> None:
        try:
            root = ET.parse(str(path)).getroot()
            for rw in root.iter():
                if rw.tag.endswith("}rewriteURI") or rw.tag == "rewriteURI":
                    start = rw.get("uriStartString", "")
                    prefix = rw.get("rewritePrefix", "")
                    if start and prefix:
                        self.rules.append((start, prefix))
        except Exception as exc:
            print(f"[TaxonomyParser] Warning: could not parse catalog {path}: {exc}")

    def resolve(self, uri: str) -> Path | None:
        if not (uri.startswith("http://") or uri.startswith("https://")):
            return None
        for start_str, prefix in sorted(self.rules, key=lambda item: len(item[0]), reverse=True):
            if uri.startswith(start_str):
                rel = uri.replace(start_str, prefix, 1)
                if self.base_dir:
                    return (self.base_dir / rel).resolve()
        return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

class TaxonomyParser:
    """Parse an NT21 taxonomy package starting from one entry-point XSD.

    Usage::

        parser = TaxonomyParser(package_dir, catalog_path)
        concepts, rules = parser.parse_entry_point(ep_file, ep_key)

    The results are suitable for building an EnrichedTaxonomyRelease.
    """

    def __init__(self, base_dir: Path, catalog_path: Path | None = None, *, strict: bool = True) -> None:
        self.base_dir = base_dir
        self.strict = strict
        self.errors: list[str] = []
        self.catalog_path = catalog_path
        self._concept_locations = {}
        self.catalog = CatalogResolver(catalog_path)
        # qname → ConceptMetadata (accumulated across all entry-point files)
        self.concepts: dict[str, ConceptMetadata] = {}
        # Namespace URI → prefix (built during XSD parsing)
        self.ns_uri_to_prefix: dict[str, str] = {}
        # rule_id → ValidationRule
        self.rules: dict[str, ValidationRule] = {}
        # Files already parsed (prevent cycles)
        self._visited: set[str] = set()
        # Current entry-point key (set per parse_entry_point call)
        self._current_ep: str = ""
        # label accumulator: localname → {role → {lang → text}}
        self._labels: dict[str, dict[str, dict[str, str]]] = {}
        # presentation arcs: (parent_href, child_href, order, role, preferred_label)
        self._pres_arcs: list[tuple[str, str, float, str, str | None]] = []
        # calc arcs
        self._calc_arcs: list[tuple[str, str, float, float, str]] = []
        # Assertion → message text accumulator
        self._msg_nl: dict[str, str] = {}
        self._msg_en: dict[str, str] = {}
        # href anchor → resolved local qname
        self._loc_map: dict[str, str] = {}
        # Taxonomy version (set from manifest)
        self.taxonomy_version: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_entry_point(
        self, ep_file: str, ep_key: str = "", taxonomy_version: str = ""
    ) -> tuple[dict[str, ConceptMetadata], list[ValidationRule]]:
        """Parse one entry point.  Returns (concepts_dict, rules_list)."""
        # Parse each entry point into an independent graph. Never seed it with another EP.
        version = taxonomy_version or self.taxonomy_version
        self.__init__(self.base_dir, self.catalog_path, strict=self.strict)
        self.taxonomy_version = version
        self._current_ep = ep_key
        self.taxonomy_version = taxonomy_version or self.taxonomy_version
        ep_path = (self.base_dir / ep_file).resolve()
        self._parse_file(ep_path)
        self._apply_labels()
        self._apply_pres_arcs()
        self._apply_calc_arcs()
        self._tag_ep_concepts(ep_key)
        return dict(self.concepts), list(self.rules.values())

    def get_requirements(self, ep_key: str) -> list[TaggingRequirement]:
        """Return legacy TaggingRequirement list for backward compatibility."""
        reqs: list[TaggingRequirement] = []
        for qname, concept in self.concepts.items():
            if ep_key not in concept.entry_points:
                continue
            if concept.abstract:
                continue
            reqs.append(TaggingRequirement(
                id=qname.replace(":", "-").lower(),
                qname=qname,
                section=concept.pres_link_role or None,
                conditional=concept.mandatory_status != "mandatory",
            ))
        return reqs

    # ------------------------------------------------------------------
    # File dispatch
    # ------------------------------------------------------------------

    def _parse_file(self, filepath: Path | None) -> None:
        if not filepath or not filepath.is_file():
            message = f"Unresolved taxonomy dependency: {filepath}"
            if self.strict:
                raise ValueError(message)
            if message not in self.errors:
                self.errors.append(message)
            return
        key = str(filepath)
        if key in self._visited:
            return
        self._visited.add(key)

        try:
            tree = ET.parse(str(filepath), ET.XMLParser(resolve_entities=False, no_network=True, remove_comments=True))
            root = tree.getroot()
        except Exception as exc:
            message = f"Cannot parse taxonomy file {filepath}: {exc}"
            if self.strict:
                raise ValueError(message) from exc
            self.errors.append(message)
            return

        tag = root.tag
        if tag.endswith("}schema") or tag == "schema":
            self._parse_schema(root, filepath)
        elif tag.endswith("}linkbase") or tag == "linkbase":
            self._parse_linkbase(root, filepath)

    def _resolve(self, href: str, current: Path) -> Path | None:
        """Resolve a linkbaseRef href to a local path."""
        if href.startswith("http://") or href.startswith("https://"):
            resolved = self.catalog.resolve(href)
            if resolved:
                return resolved
            # Fall back to stripping fragment and treating as local
            url, _ = urllib.parse.urldefrag(href)
            resolved = self.catalog.resolve(url)
            if resolved is None and not self.strict:
                message = f"Unresolved taxonomy URI: {href}"
                if message not in self.errors:
                    self.errors.append(message)
            return resolved
        # Relative path
        url, _ = urllib.parse.urldefrag(href)
        return (current.parent / url).resolve() if url else None

    # ------------------------------------------------------------------
    # XSD schema parsing
    # ------------------------------------------------------------------

    def _parse_schema(self, root: ET.Element, filepath: Path) -> None:
        target_ns = root.get("targetNamespace", "")

        prefix = self._prefix_for(target_ns, root)

        # Extract concept elements
        for el in root.iter("{http://www.w3.org/2001/XMLSchema}element"):
            name = el.get("name")
            if not name:
                continue
            subgroup = el.get("substitutionGroup", "")
            # Only include XBRL items (xbrli:item or tuple)
            if "item" not in subgroup and "tuple" not in subgroup:
                continue

            qname = f"{prefix}:{name}"
            self._concept_locations[f"{filepath.resolve()}#{el.get('id', name)}"] = qname
            if qname not in self.concepts:
                self.concepts[qname] = ConceptMetadata(
                    qname=qname,
                    namespace=target_ns,
                    local_name=name,
                    taxonomy_version=self.taxonomy_version,
                    data_type=el.get("type", ""),
                    period_type=el.get("{http://www.xbrl.org/2003/instance}periodType", ""),
                    balance=el.get("{http://www.xbrl.org/2003/instance}balance"),
                    abstract=el.get("abstract", "false").lower() == "true",
                    nillable=el.get("nillable", "true").lower() == "true",
                    substitution_group=subgroup,
                    entry_points=[],
                )

        # Follow schema imports and includes.
        for imp in list(root.iter("{http://www.w3.org/2001/XMLSchema}import")) + list(root.iter("{http://www.w3.org/2001/XMLSchema}include")):
            loc = imp.get("schemaLocation", "")
            if loc:
                self._parse_file(self._resolve(loc, filepath))

        # Follow linkbaseRef
        for lb in root.iter("{http://www.xbrl.org/2003/linkbase}linkbaseRef"):
            href = lb.get("{http://www.w3.org/1999/xlink}href", "")
            if href:
                self._parse_file(self._resolve(href, filepath))

    # ------------------------------------------------------------------
    # Linkbase routing
    # ------------------------------------------------------------------

    def _parse_linkbase(self, root: ET.Element, filepath: Path) -> None:
        # Parse xsi:schemaLocation to discover concept XSD files referenced
        # from this linkbase (NT21 linkbases reference concept schemas this way)
        schema_loc = root.get(
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", ""
        )
        if schema_loc:
            # schemaLocation is pairs: namespace1 uri1 namespace2 uri2 ...
            parts = schema_loc.split()
            for i in range(0, len(parts) - 1, 2):
                ns_uri = parts[i]
                schema_uri = parts[i + 1]
                # Only parse local NT taxonomy schemas (skip XBRL core schemas)
                if schema_uri.startswith("http://") or schema_uri.startswith("https://"):
                    resolved = self.catalog.resolve(schema_uri)
                    if resolved and resolved.exists() and resolved.suffix == ".xsd":
                        self._parse_file(resolved)
                else:
                    resolved = self._resolve(schema_uri, filepath)
                    if resolved and resolved.exists() and resolved.suffix == ".xsd":
                        self._parse_file(resolved)

        # First pass: build loc map (label → resolved qname)
        self._loc_map = {}
        self._build_loc_map(root, filepath)
        # Locators carry file-qualified IDs, not globally unique fragments.
        for loc in root.iter("{http://www.xbrl.org/2003/linkbase}loc"):
            href = loc.get("{http://www.w3.org/1999/xlink}href", "")
            if "#" in href:
                url, fragment = href.rsplit("#", 1)
                resolved = self._resolve(url, filepath) if url else filepath
                if resolved:
                    loc.set("{http://www.w3.org/1999/xlink}href", f"{resolved.resolve()}#{fragment}")

        # Route by child element types present
        tags_present = {el.tag for el in root.iter()}

        if any(t.endswith("}labelArc") for t in tags_present):
            self._parse_label_linkbase(root)

        if any(t.endswith("}presentationArc") for t in tags_present):
            self._parse_presentation_linkbase(root)

        if any(t.endswith("}calculationArc") for t in tags_present):
            self._parse_calculation_linkbase(root)

        if any("existenceAssertion" in t or "valueAssertion" in t for t in tags_present):
            self._parse_formula_linkbase(root, filepath)

        if any(t.endswith("}message") for t in tags_present):
            self._parse_message_linkbase(root)

        # Follow further linkbaseRefs inside linkbases (some NT files do this)
        for lb in root.iter("{http://www.xbrl.org/2003/linkbase}linkbaseRef"):
            href = lb.get("{http://www.w3.org/1999/xlink}href", "")
            if href:
                self._parse_file(self._resolve(href, filepath))

    def _build_loc_map(self, root: ET.Element, filepath: Path) -> None:
        """Map xlink:label attributes to qnames by resolving href anchors."""
        loc_map = {}
        for loc in root.iter("{http://www.xbrl.org/2003/linkbase}loc"):
            href = loc.get("{http://www.w3.org/1999/xlink}href", "")
            label = loc.get("{http://www.w3.org/1999/xlink}label", "")
            if "#" in href:
                url, fragment = href.rsplit("#", 1)
                resolved = self._resolve(url, filepath) if url else filepath
                # The fragment is the element id; we'll look it up by name
                if resolved:
                    loc_map[label] = f"{resolved.resolve()}#{fragment}"
                    if resolved.suffix == ".xsd":
                        self._parse_file(resolved)

        self._loc_map = loc_map

    # ------------------------------------------------------------------
    # Label linkbase
    # ------------------------------------------------------------------

    def _parse_label_linkbase(self, root: ET.Element) -> None:
        # Gather labels: id → {role → {lang → text}}
        id_to_labels: dict[str, dict[str, dict[str, str]]] = {}
        for lbl in root.iter("{http://www.xbrl.org/2003/linkbase}label"):
            role = lbl.get("{http://www.w3.org/1999/xlink}role", _LABEL_ROLE_STANDARD)
            lang = lbl.get("{http://www.w3.org/XML/1998/namespace}lang", "nl")
            lbl_id = lbl.get("{http://www.w3.org/1999/xlink}label", "")
            text = (lbl.text or "").strip()
            if lbl_id and text:
                id_to_labels.setdefault(lbl_id, {}).setdefault(role, {})[lang] = text

        # Walk labelArc to connect loc labels → actual labels
        for arc in root.iter("{http://www.xbrl.org/2003/linkbase}labelArc"):
            from_label = arc.get("{http://www.w3.org/1999/xlink}from", "")
            to_label = arc.get("{http://www.w3.org/1999/xlink}to", "")
            fragment = self._loc_map.get(from_label, "")
            if fragment and to_label in id_to_labels:
                self._labels.setdefault(fragment, {})
                for role, langs in id_to_labels[to_label].items():
                    self._labels[fragment].setdefault(role, {}).update(langs)

    def _apply_labels(self) -> None:
        """Push accumulated labels into ConceptMetadata objects.

        The _labels dict is keyed by the fragment identifier extracted from
        xlink:href in label locs.  In NT21 these have the format:
          jenv-bw2-i_Assets  (prefix_LocalName)
          kvk-i_Assets       (prefix_LocalName)
          Assets             (just local name)

        We must match against concept.local_name by stripping any prefix.
        """
        for frag_key, roles in self._labels.items():
            qname = self._concept_locations.get(frag_key)
            concepts_for_label = [self.concepts[qname]] if qname in self.concepts else []
            for concept in concepts_for_label:
                nl_label = (
                    roles.get(_LABEL_ROLE_VERBOSE, {}).get("nl")
                    or roles.get(_LABEL_ROLE_STANDARD, {}).get("nl")
                    or ""
                )
                en_label = (
                    roles.get(_LABEL_ROLE_VERBOSE, {}).get("en")
                    or roles.get(_LABEL_ROLE_STANDARD, {}).get("en")
                    or ""
                )
                doc = roles.get(_LABEL_ROLE_DOC, {}).get("nl") or ""
                # ConceptMetadata is mutable (not frozen); only set if not already set
                if not concept.label_nl and nl_label:
                    concept.label_nl = nl_label
                if not concept.label_en and en_label:
                    concept.label_en = en_label
                if not concept.documentation and doc:
                    concept.documentation = doc


    # ------------------------------------------------------------------
    # Presentation linkbase
    # ------------------------------------------------------------------

    def _parse_presentation_linkbase(self, root: ET.Element) -> None:
        for link in root.iter("{http://www.xbrl.org/2003/linkbase}presentationLink"):
            role = link.get("{http://www.w3.org/1999/xlink}role", "")
            locs: dict[str, str] = {}
            for loc in link.iter("{http://www.xbrl.org/2003/linkbase}loc"):
                lbl = loc.get("{http://www.w3.org/1999/xlink}label", "")
                href = loc.get("{http://www.w3.org/1999/xlink}href", "")
                if "#" in href:
                    fragment = href
                    locs[lbl] = fragment
            for arc in link.iter("{http://www.xbrl.org/2003/linkbase}presentationArc"):
                from_lbl = arc.get("{http://www.w3.org/1999/xlink}from", "")
                to_lbl = arc.get("{http://www.w3.org/1999/xlink}to", "")
                order = float(arc.get("order", "0"))
                pref_label = arc.get("preferredLabel")
                parent_frag = locs.get(from_lbl, "")
                child_frag = locs.get(to_lbl, "")
                if parent_frag and child_frag:
                    self._pres_arcs.append((parent_frag, child_frag, order, role, pref_label))

    def _apply_pres_arcs(self) -> None:
        """Map presentation fragments → concept metadata."""
        # Build fragment → concept lookup
        frag_to_concept: dict[str, ConceptMetadata] = {
            loc: self.concepts[qn] for loc, qn in self._concept_locations.items() if qn in self.concepts
        }
        for parent_frag, child_frag, order, role, pref in self._pres_arcs:
            child = frag_to_concept.get(child_frag)
            parent = frag_to_concept.get(parent_frag)
            if child:
                child.pres_order = order
                child.pres_link_role = child.pres_link_role or role
                if parent:
                    child.parent_qname = parent.qname
                    if child.qname not in parent.pres_children:
                        parent.pres_children.append(child.qname)

    # ------------------------------------------------------------------
    # Calculation linkbase
    # ------------------------------------------------------------------

    def _parse_calculation_linkbase(self, root: ET.Element) -> None:
        for link in root.iter("{http://www.xbrl.org/2003/linkbase}calculationLink"):
            role = link.get("{http://www.w3.org/1999/xlink}role", "")
            locs: dict[str, str] = {}
            for loc in link.iter("{http://www.xbrl.org/2003/linkbase}loc"):
                lbl = loc.get("{http://www.w3.org/1999/xlink}label", "")
                href = loc.get("{http://www.w3.org/1999/xlink}href", "")
                if "#" in href:
                    frag = href
                    locs[lbl] = frag
            for arc in link.iter("{http://www.xbrl.org/2003/linkbase}calculationArc"):
                from_lbl = arc.get("{http://www.w3.org/1999/xlink}from", "")
                to_lbl = arc.get("{http://www.w3.org/1999/xlink}to", "")
                weight = float(arc.get("weight", "1"))
                order = float(arc.get("order", "0"))
                self._calc_arcs.append((locs.get(from_lbl, ""), locs.get(to_lbl, ""), weight, order, role))

    def _apply_calc_arcs(self) -> None:
        frag_to_concept: dict[str, ConceptMetadata] = {
            loc: self.concepts[qn] for loc, qn in self._concept_locations.items() if qn in self.concepts
        }
        for parent_frag, child_frag, weight, order, role in self._calc_arcs:
            parent = frag_to_concept.get(parent_frag)
            child = frag_to_concept.get(child_frag)
            if parent and child:
                arc = CalcRelationship(
                    parent_qname=parent.qname,
                    child_qname=child.qname,
                    weight=weight,
                    order=order,
                    link_role=role,
                )
                if arc not in parent.calc_relationships:
                    parent.calc_relationships.append(arc)

    # ------------------------------------------------------------------
    # Formula linkbase (CRITICAL: determines mandatory/conditional status)
    # ------------------------------------------------------------------

    def _parse_formula_linkbase(self, root: ET.Element, filepath: Path) -> None:
        """Extract ea:existenceAssertion and va:valueAssertion elements.

        ea:existenceAssertion with test='.eq 0' means: 'if zero facts exist
        for this concept → assertion fails' → concept is MANDATORY.

        If the assertion is connected to a boolean-filter (bf:andFilter/
        bf:orFilter) we mark it CONDITIONAL and capture the filter chain
        as the condition description.

        va:valueAssertion encodes calculation constraints (e.g. parent = sum
        of children).  These become CALCULATION rules.
        """
        ep = self._current_ep
        fname = filepath.name

        # --- existence assertions ---
        for ea in root.iter("{http://xbrl.org/2008/assertion/existence}existenceAssertion"):
            rule_id = ea.get("id", "")
            test = ea.get("test", "")
            # Check for boolean-filter parents (indicates conditionality)
            # In NT21, all top-level existenceAssertions in a gen:link are
            # unconditional unless explicitly gated.
            # We determine conditionality by checking whether there is any
            # bf:andFilter / bf:orFilter in the same linkbase that references
            # this assertion.
            is_conditional = self._is_assertion_conditional(root, rule_id)
            status = MandatoryStatus.CONDITIONAL if is_conditional else MandatoryStatus.MANDATORY

            # Find the concept this assertion targets (via variable:variableFilterArc → cf:conceptName)
            concept_qname = self._find_assertion_concept(root, rule_id)

            condition_nl = ""
            if is_conditional:
                condition_nl = "Verplicht wanneer van toepassing"

            rule = ValidationRule(
                rule_id=rule_id,
                rule_type=RuleType.EXISTENCE,
                status=status,
                concept_qname=concept_qname,
                test_expression=test,
                condition_nl=condition_nl,
                condition_en="Required when applicable" if is_conditional else "",
                entry_points=(ep,) if ep else (),
                source_file=fname,
                taxonomy_version=self.taxonomy_version,
            )

            if rule_id not in self.rules:
                self.rules[rule_id] = rule
            else:
                # Merge entry points
                existing = self.rules[rule_id]
                merged_eps = tuple(set(existing.entry_points) | {ep}) if ep else existing.entry_points
                self.rules[rule_id] = ValidationRule(
                    rule_id=existing.rule_id,
                    rule_type=existing.rule_type,
                    status=existing.status,
                    concept_qname=existing.concept_qname,
                    test_expression=existing.test_expression,
                    condition_nl=existing.condition_nl,
                    condition_en=existing.condition_en,
                    entry_points=merged_eps,
                    source_file=existing.source_file,
                    taxonomy_version=existing.taxonomy_version,
                )

            # Update concept's mandatory status
            if concept_qname and concept_qname in self.concepts:
                c = self.concepts[concept_qname]
                # Upgrade: optional → conditional → mandatory
                if status == MandatoryStatus.MANDATORY:
                    c.mandatory_status = "mandatory"
                elif status == MandatoryStatus.CONDITIONAL and c.mandatory_status == "optional":
                    c.mandatory_status = "conditional"
                if rule_id not in c.rule_ids:
                    c.rule_ids.append(rule_id)
                if condition_nl and not c.condition_nl:
                    c.condition_nl = condition_nl

        # --- value assertions (calculation rules) ---
        for va in root.iter("{http://xbrl.org/2008/assertion/value}valueAssertion"):
            rule_id = va.get("id", "")
            test = va.get("test", "")
            if rule_id and rule_id not in self.rules:
                self.rules[rule_id] = ValidationRule(
                    rule_id=rule_id,
                    rule_type=RuleType.VALUE,
                    status=MandatoryStatus.OPTIONAL,   # value assertions don't make concepts mandatory
                    concept_qname=None,
                    test_expression=test[:500],
                    entry_points=(ep,) if ep else (),
                    source_file=fname,
                    taxonomy_version=self.taxonomy_version,
                )

    def _is_assertion_conditional(self, root: ET.Element, assertion_id: str) -> bool:
        """Check whether the assertion is referenced inside a boolean-filter."""
        for bf in root.iter():
            tag = bf.tag
            if "andFilter" in tag or "orFilter" in tag:
                # Check if any child arc targets this assertion
                for arc in bf:
                    ref = arc.get("{http://www.w3.org/1999/xlink}to", "")
                    if assertion_id in ref:
                        return True
        return False

    def _find_assertion_concept(self, root: ET.Element, assertion_id: str) -> str | None:
        """Find the concept qname targeted by an existenceAssertion.

        In NT21 formula linkbases the pattern is:
          existenceAssertion → (variableArc arcrole=variable-set) → factVariable
          factVariable → (variableFilterArc) → cf:conceptName filter
        The cf:conceptName filter contains the concept qname element with the prefix:localName.
        """
        xl = "{http://www.w3.org/1999/xlink}"
        assertion = next((el for el in root.iter() if el.get("id") == assertion_id), None)
        label = assertion.get(xl + "label", assertion_id) if assertion is not None else assertion_id
        variables = {a.get(xl + "to") for a in root.findall(".//variable:variableArc", NS)
                     if a.get(xl + "from") == label}
        filters = {a.get(xl + "to") for a in root.findall(".//variable:variableFilterArc", NS)
                   if a.get(xl + "from") in variables}
        matches = set()
        for cf in root.findall(".//cf:conceptName", NS):
            if cf.get(xl + "label") not in filters:
                continue
            for child in cf.iter():
                raw = (child.text or "").strip()
                if ":" not in raw:
                    continue
                alias, local = raw.split(":", 1)
                uri = child.nsmap.get(alias)
                if uri:
                    qname = self._prefix_for(uri, child) + ":" + local
                    if qname in self.concepts:
                        matches.add(qname)
        return next(iter(matches)) if len(matches) == 1 else None

    def _prefix_for(self, uri, element):
        if uri not in self.ns_uri_to_prefix:
            proposed = next((p for p, u in element.nsmap.items() if p and u == uri), None)
            used = set(self.ns_uri_to_prefix.values())
            if not proposed or proposed in used:
                proposed = "ns" + sha256(uri.encode()).hexdigest()[:12]
            self.ns_uri_to_prefix[uri] = proposed
        return self.ns_uri_to_prefix[uri]

    # ------------------------------------------------------------------
    # Message linkbase (assertion-unsatisfied-message)
    # ------------------------------------------------------------------

    def _parse_message_linkbase(self, root: ET.Element) -> None:
        """Extract Dutch/English error messages for assertions."""
        for msg in root.iter("{http://xbrl.org/2010/message}message"):
            lang = msg.get("{http://www.w3.org/XML/1998/namespace}lang", "nl")
            lbl = msg.get("{http://www.w3.org/1999/xlink}label", "")
            text = (msg.text or "").strip()
            if lbl and text:
                if lang == "nl":
                    self._msg_nl[lbl] = text
                elif lang == "en":
                    self._msg_en[lbl] = text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _tag_ep_concepts(self, ep_key: str) -> None:
        """Mark all parsed concepts as belonging to this entry point."""
        for concept in self.concepts.values():
            if ep_key and ep_key not in concept.entry_points:
                concept.entry_points.append(ep_key)
