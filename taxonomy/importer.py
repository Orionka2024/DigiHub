"""TaxonomyImporter – full Nederlandse Taxonomie linkbase parser.

Reads an official KVK/NT taxonomy package from disk and produces:
  - A dict of ConceptMetadata objects (one per non-abstract element)
  - Dutch/English labels from label linkbases
  - Mandatory/conditional status from formula (assertion) linkbases
  - Presentation hierarchy (ordered, grouped by link role)
  - Calculation weights

Usage::

    from taxonomy.importer import TaxonomyImporter

    importer = TaxonomyImporter(package_path, catalog_path)
    concepts = importer.import_entry_point("groot_nlgaap", entry_xsd_path)
    # concepts: dict[qname, ConceptMetadata]

Design notes:
  - The catalog.xml OASIS XML Catalog maps http:// URIs → local paths.
  - We walk the XSD import/include graph and every linkbaseRef encountered.
  - Label linkbases are parsed for all languages and all label roles.
  - Formula linkbases (*-for.xml) are parsed for ea:existenceAssertion and
    va:valueAssertion to derive mandatory / conditional status.
  - Presentation linkbases are parsed to build the ordered hierarchy and
    assign link roles (section names) to concepts.
  - Calculation linkbases are parsed to build parent/child weight maps.
"""
from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from lxml import etree

from .concept import ConceptMetadata
from .assertion import AssertionRule

# ── XML namespace constants ────────────────────────────────────────────────────
NS_XSD   = "http://www.w3.org/2001/XMLSchema"
NS_LINK  = "http://www.xbrl.org/2003/linkbase"
NS_XLINK = "http://www.w3.org/1999/xlink"
NS_GEN   = "http://xbrl.org/2008/generic"
NS_EA    = "http://xbrl.org/2008/assertion/existence"
NS_VA    = "http://xbrl.org/2008/assertion/value"
NS_VAR   = "http://xbrl.org/2008/variable"
NS_CF    = "http://xbrl.org/2008/filter/concept"
NS_SEVE  = "http://www.xbrl.org/2016/assertion-severity"
NS_CAT   = "urn:oasis:names:tc:entity:xmlns:xml:catalog"

# XBRL label roles
ROLE_LABEL         = "http://www.xbrl.org/2003/role/label"
ROLE_TERSE         = "http://www.xbrl.org/2003/role/terseLabel"
ROLE_VERBOSE       = "http://www.xbrl.org/2003/role/verboseLabel"
ROLE_TOTAL         = "http://www.xbrl.org/2003/role/totalLabel"
ROLE_DOC           = "http://www.xbrl.org/2003/role/documentation"
ROLE_DOMAIN_MEMBER = "http://www.xbrl.org/2003/role/domainMemberLabel"

# Assertion severity URIs
SEVE_ERROR   = "http://www.xbrl.org/2016/severities.xml#ERROR"
SEVE_WARNING = "http://www.xbrl.org/2016/severities.xml#WARNING"
SEVE_OK      = "http://www.xbrl.org/2016/severities.xml#OK"


class CatalogResolver:
    """Resolves http:// taxonomy URIs to local file paths via OASIS catalog."""

    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path
        self.rules: list[tuple[str, str]] = []
        if catalog_path and catalog_path.exists():
            self._parse()

    def _parse(self) -> None:
        try:
            root = etree.parse(str(self.catalog_path)).getroot()
            for rw in root.findall(f".//{{{NS_CAT}}}rewriteURI"):
                start = rw.get("uriStartString")
                prefix = rw.get("rewritePrefix")
                if start and prefix:
                    self.rules.append((start, prefix))
        except Exception as exc:
            print(f"[TaxonomyImporter] catalog parse error: {exc}")

    def resolve(self, uri: str, relative_to: Path | None = None) -> Path | None:
        if not (uri.startswith("http://") or uri.startswith("https://")):
            if relative_to:
                return (relative_to.parent / uri).resolve()
            return None
        for start, prefix in self.rules:
            if uri.startswith(start):
                rel = uri.replace(start, prefix, 1)
                return (self.catalog_path.parent / rel).resolve()
        return None

    def resolve_href(self, href: str, current_file: Path) -> Path | None:
        """Resolve an href that may be absolute URI or relative path."""
        # Strip fragment
        url, _ = urllib.parse.urldefrag(href)
        if url.startswith("http://") or url.startswith("https://"):
            return self.resolve(url)
        return (current_file.parent / url).resolve()


class TaxonomyImporter:
    """
    Imports a complete XBRL taxonomy entry point into ConceptMetadata objects.

    Parameters
    ----------
    package_dir : Path
        Root of the taxonomy package directory
        (the folder containing META-INF/ and taxonomie/).
    catalog_path : Path | None
        Path to META-INF/catalog.xml.  If None, no URI rewriting is done.
    taxonomy_version : str
        Version string stored on every ConceptMetadata (e.g. "NT21_KVK_20261209_b").
    """

    def __init__(
        self,
        package_dir: Path,
        catalog_path: Path | None = None,
        taxonomy_version: str = "",
    ) -> None:
        self.package_dir = package_dir
        self.catalog = CatalogResolver(catalog_path) if catalog_path else CatalogResolver.__new__(CatalogResolver)
        if not catalog_path:
            self.catalog.rules = []
            self.catalog.catalog_path = package_dir / "META-INF" / "catalog.xml"
        self.taxonomy_version = taxonomy_version

        # ── Shared state populated during a parse run ──────────────────────────
        self._visited: set[str] = set()          # absolute paths already parsed
        self._nsmap: dict[str, str] = {}          # prefix → namespace URI

        # Raw element declarations from XSD: qname → lxml Element
        self._elements: dict[str, etree._Element] = {}

        # Labels: qname → {lang+role → text}
        # e.g. labels["jenv-bw2-i:Assets"]["nl:label"] = "Activa"
        self._labels: dict[str, dict[str, str]] = {}

        # Assertions: assertion_id → AssertionRule (before concept resolution)
        self._assertions: dict[str, AssertionRule] = {}

        # Maps assertion locator label → qname (resolved from concept-filter)
        self._assertion_concepts: dict[str, str] = {}

        # Maps assertion id → severity ("ERROR"/"WARNING")
        self._assertion_severity: dict[str, str] = {}

        # Maps assertion id → list[precondition_qname]
        self._assertion_preconditions: dict[str, list[str]] = {}

        # Presentation: qname → (link_role, parent_qname, order, depth)
        self._presentation: dict[str, dict[str, Any]] = {}

        # Calculation: qname → {parent_qname: weight}
        self._calculation: dict[str, dict[str, float]] = {}

        # Which entry point keys include each qname
        self._concept_entry_points: dict[str, list[str]] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def import_entry_point(
        self, entry_key: str, entry_xsd: str
    ) -> dict[str, ConceptMetadata]:
        """
        Parse one entry point XSD (and all linked files) and return a dict
        mapping QName → ConceptMetadata.

        This method can be called multiple times for different entry points;
        each call accumulates labels/hierarchy but tracks which entry points
        include which concept.
        """
        entry_path = self.package_dir / entry_xsd
        self._parse_file(entry_path, entry_key=entry_key)
        return self._build_concepts(entry_key)

    def get_all_concepts(self) -> dict[str, ConceptMetadata]:
        """Return all concepts accumulated across all parsed entry points."""
        return self._build_concepts(entry_key=None)

    # ─────────────────────────────────────────────────────────────────────────
    # File dispatcher
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_file(self, filepath: Path | None, entry_key: str | None = None) -> None:
        if not filepath:
            return
        filepath = filepath.resolve()
        key = str(filepath)
        if key in self._visited or not filepath.exists():
            return
        self._visited.add(key)

        try:
            tree = etree.parse(str(filepath))
        except Exception as exc:
            print(f"[TaxonomyImporter] XML parse error {filepath.name}: {exc}")
            return

        root = tree.getroot()
        local = root.tag.split("}")[-1] if "}" in root.tag else root.tag

        # Accumulate namespaces
        for pfx, uri in root.nsmap.items():
            if pfx and uri and pfx not in self._nsmap:
                self._nsmap[pfx] = uri

        if local == "schema":
            self._parse_schema(root, filepath, entry_key)
        elif local == "linkbase":
            self._parse_linkbase(root, filepath, entry_key)

    # ─────────────────────────────────────────────────────────────────────────
    # XSD schema parsing
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_schema(
        self, root: etree._Element, filepath: Path, entry_key: str | None
    ) -> None:
        ns = {"xsd": NS_XSD, "link": NS_LINK}
        target_ns = root.get("targetNamespace", "")
        prefix = self._prefix_for_ns(target_ns)

        # ── Extract element declarations ──────────────────────────────────────
        for el in root.findall(".//xsd:element", namespaces=ns):
            name = el.get("name")
            sub_grp = el.get("substitutionGroup", "")
            # Only concrete items (not abstract, must have substitutionGroup containing "item" or "tuple")
            if name and prefix and ("item" in sub_grp or "tuple" in sub_grp):
                qname = f"{prefix}:{name}"
                if qname not in self._elements:
                    self._elements[qname] = el
                # Track which entry point includes this concept
                if entry_key:
                    self._concept_entry_points.setdefault(qname, [])
                    if entry_key not in self._concept_entry_points[qname]:
                        self._concept_entry_points[qname].append(entry_key)

        # ── Follow xsd:import ─────────────────────────────────────────────────
        for imp in root.findall(".//xsd:import", namespaces=ns):
            loc = imp.get("schemaLocation")
            if loc:
                resolved = self.catalog.resolve_href(loc, filepath)
                self._parse_file(resolved, entry_key)

        # ── Follow linkbaseRef ────────────────────────────────────────────────
        for lb in root.findall(".//link:linkbaseRef", namespaces=ns):
            href = lb.get(f"{{{NS_XLINK}}}href")
            if href:
                resolved = self.catalog.resolve_href(href, filepath)
                self._parse_file(resolved, entry_key)

    # ─────────────────────────────────────────────────────────────────────────
    # Linkbase routing
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_linkbase(
        self, root: etree._Element, filepath: Path, entry_key: str | None
    ) -> None:
        ns_link = {"link": NS_LINK, "xlink": NS_XLINK}

        # Follow any nested linkbaseRefs (unusual but possible)
        for lb in root.findall(".//link:linkbaseRef", namespaces=ns_link):
            href = lb.get(f"{{{NS_XLINK}}}href")
            if href:
                resolved = self.catalog.resolve_href(href, filepath)
                self._parse_file(resolved, entry_key)

        # Detect linkbase type by child elements present
        children = {el.tag.split("}")[-1] if "}" in el.tag else el.tag
                    for el in root}

        fname = filepath.name.lower()

        if "labelLink" in children or "-lab-" in fname:
            self._parse_label_linkbase(root, filepath)
        elif "presentationLink" in children or "-pre" in fname:
            self._parse_presentation_linkbase(root, filepath)
        elif "calculationLink" in children or "-cal" in fname:
            self._parse_calculation_linkbase(root, filepath)
        elif "definitionLink" in children or "-def" in fname:
            # Definition linkbases: follow schema refs to discover concepts
            self._parse_definition_linkbase(root, filepath, entry_key)
        else:
            # Could be generic formula linkbase (*-for.xml)
            self._parse_formula_linkbase(root, filepath, entry_key)

    # ─────────────────────────────────────────────────────────────────────────
    # Label linkbase
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_label_linkbase(self, root: etree._Element, filepath: Path) -> None:
        """Extract labels from link:labelLink elements."""
        ns = {"link": NS_LINK, "xlink": NS_XLINK}

        for label_link in root.findall(f"{{{NS_LINK}}}labelLink"):
            # Build loc table: label-attr → concept href
            locs: dict[str, str] = {}
            for loc in label_link.findall(f"{{{NS_LINK}}}loc"):
                lbl = loc.get(f"{{{NS_XLINK}}}label", "")
                href = loc.get(f"{{{NS_XLINK}}}href", "")
                # href is e.g. "jenv-bw2-data.xsd#jenv-bw2-i_Assets"
                _, _, fragment = href.rpartition("#")
                if fragment:
                    locs[lbl] = fragment  # store element id

            # Build label table: label-attr → (role, lang, text)
            labels: dict[str, tuple[str, str, str]] = {}
            for lbl_el in label_link.findall(f"{{{NS_LINK}}}label"):
                lbl_id = lbl_el.get(f"{{{NS_XLINK}}}label", "")
                role   = lbl_el.get(f"{{{NS_XLINK}}}role", ROLE_LABEL)
                lang   = lbl_el.get("{http://www.w3.org/XML/1998/namespace}lang", "nl")
                text   = (lbl_el.text or "").strip()
                if text:
                    labels[lbl_id] = (role, lang, text)

            # Wire arcs: from=loc_label, to=label_label
            for arc in label_link.findall(f"{{{NS_LINK}}}labelArc"):
                from_lbl = arc.get(f"{{{NS_XLINK}}}from", "")
                to_lbl   = arc.get(f"{{{NS_XLINK}}}to", "")
                elem_id  = locs.get(from_lbl, "")
                label_data = labels.get(to_lbl)
                if not elem_id or not label_data:
                    continue

                role, lang, text = label_data
                # Convert element id (e.g. "jenv-bw2-i_Assets") → qname
                qname = self._elem_id_to_qname(elem_id)
                if not qname:
                    continue

                store = self._labels.setdefault(qname, {})
                key = f"{lang}:{self._role_short(role)}"
                store[key] = text

    def _elem_id_to_qname(self, elem_id: str) -> str | None:
        """Convert XSD element id (e.g. jenv-bw2-i_Assets) to QName."""
        # Fragment format: prefix_LocalName  (first underscore is separator)
        # BUT some ids have multiple underscores.
        # Strategy: split on FIRST underscore-less prefix match in our nsmap.
        # Fallback: replace first "_" with ":"
        if "_" not in elem_id:
            return None
        # Try to find longest matching prefix
        for pfx in sorted(self._nsmap.keys(), key=len, reverse=True):
            candidate = f"{pfx}_"
            if elem_id.startswith(candidate):
                local = elem_id[len(candidate):]
                return f"{pfx}:{local}"
        # Fallback: first underscore
        idx = elem_id.index("_")
        pfx = elem_id[:idx]
        local = elem_id[idx+1:]
        if pfx in self._nsmap:
            return f"{pfx}:{local}"
        return None

    def _role_short(self, role: str) -> str:
        """Convert full role URI to a short key."""
        mapping = {
            ROLE_LABEL:  "label",
            ROLE_TERSE:  "terse",
            ROLE_VERBOSE: "verbose",
            ROLE_TOTAL:  "total",
            ROLE_DOC:    "doc",
            ROLE_DOMAIN_MEMBER: "domain",
        }
        return mapping.get(role, role.rsplit("/", 1)[-1].rsplit("#", 1)[-1])

    # ─────────────────────────────────────────────────────────────────────────
    # Presentation linkbase
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_presentation_linkbase(self, root: etree._Element, filepath: Path) -> None:
        """Build ordered hierarchy from link:presentationLink."""
        for plink in root.findall(f"{{{NS_LINK}}}presentationLink"):
            role = plink.get(f"{{{NS_XLINK}}}role", "")

            # Build loc table: label → (href, qname)
            locs: dict[str, str] = {}  # label → qname
            for loc in plink.findall(f"{{{NS_LINK}}}loc"):
                lbl  = loc.get(f"{{{NS_XLINK}}}label", "")
                href = loc.get(f"{{{NS_XLINK}}}href", "")
                _, _, frag = href.rpartition("#")
                qname = self._elem_id_to_qname(frag) if frag else None
                if lbl and qname:
                    locs[lbl] = qname

            # Process arcs
            for arc in plink.findall(f"{{{NS_LINK}}}presentationArc"):
                from_lbl = arc.get(f"{{{NS_XLINK}}}from", "")
                to_lbl   = arc.get(f"{{{NS_XLINK}}}to", "")
                order    = float(arc.get("order", "0") or "0")
                parent_q = locs.get(from_lbl)
                child_q  = locs.get(to_lbl)
                if not parent_q or not child_q:
                    continue

                existing = self._presentation.get(child_q, {})
                # Only update if this is a better (primary) role or no entry yet
                if not existing or role == existing.get("link_role"):
                    self._presentation[child_q] = {
                        "link_role": role,
                        "parent_qname": parent_q,
                        "order": order,
                        "depth": existing.get("depth", 0),
                    }

    # ─────────────────────────────────────────────────────────────────────────
    # Calculation linkbase
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_calculation_linkbase(self, root: etree._Element, filepath: Path) -> None:
        """Build parent-child weight map from link:calculationLink."""
        for clink in root.findall(f"{{{NS_LINK}}}calculationLink"):
            locs: dict[str, str] = {}
            for loc in clink.findall(f"{{{NS_LINK}}}loc"):
                lbl  = loc.get(f"{{{NS_XLINK}}}label", "")
                href = loc.get(f"{{{NS_XLINK}}}href", "")
                _, _, frag = href.rpartition("#")
                qname = self._elem_id_to_qname(frag) if frag else None
                if lbl and qname:
                    locs[lbl] = qname

            for arc in clink.findall(f"{{{NS_LINK}}}calculationArc"):
                from_lbl = arc.get(f"{{{NS_XLINK}}}from", "")
                to_lbl   = arc.get(f"{{{NS_XLINK}}}to", "")
                weight   = float(arc.get("weight", "1") or "1")
                parent_q = locs.get(from_lbl)
                child_q  = locs.get(to_lbl)
                if parent_q and child_q:
                    self._calculation.setdefault(child_q, {})[parent_q] = weight

    # ─────────────────────────────────────────────────────────────────────────
    # Definition linkbase  (used to discover concepts via schema refs)
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_definition_linkbase(
        self, root: etree._Element, filepath: Path, entry_key: str | None
    ) -> None:
        """Follow locator hrefs in definition linkbases to load XSDs."""
        for dlink in root.findall(f"{{{NS_LINK}}}definitionLink"):
            for loc in dlink.findall(f"{{{NS_LINK}}}loc"):
                href = loc.get(f"{{{NS_XLINK}}}href", "")
                url, _, _ = href.rpartition("#")
                if url:
                    resolved = self.catalog.resolve_href(url, filepath)
                    self._parse_file(resolved, entry_key)

    # ─────────────────────────────────────────────────────────────────────────
    # Formula / assertion linkbase  (*-for.xml)
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_formula_linkbase(
        self, root: etree._Element, filepath: Path, entry_key: str | None
    ) -> None:
        """
        Parse XBRL Formula linkbases to extract ea:existenceAssertion and
        va:valueAssertion nodes with their concept filters and severity.

        NT21 pattern:
          gen:link
            ea:existenceAssertion id="..." test=".eq 1"
            cf:conceptName id="..._ConceptQName"  ← tells us WHICH concept
            gen:arc arcrole=assertion-unsatisfied-severity from=assertionId to=ERROR_loc
            gen:arc arcrole=variable-set from=assertionId to=factVariableId
            variable:variableArc arcrole=variable-filter from=factVariableId to=conceptNameId
        """
        source_name = filepath.name

        # ── Step 1: collect all concept-name filter resources ────────────────
        # id → qname string
        concept_filters: dict[str, str] = {}
        for cf_el in root.findall(f".//{{{NS_CF}}}conceptName"):
            cf_id = cf_el.get("id", "")
            qn_el = cf_el.find(f"{{{NS_CF}}}concept/{{{NS_CF}}}qname")
            if cf_id and qn_el is not None and qn_el.text:
                concept_filters[cf_id] = qn_el.text.strip()

        # ── Step 2: collect severity arcs: assertion_id → "ERROR"/"WARNING" ──
        severity_map: dict[str, str] = {}
        for arc in root.findall(f".//{{{NS_GEN}}}arc[@*]"):
            arcrole = arc.get(f"{{{NS_XLINK}}}arcrole", "")
            if "assertion-unsatisfied-severity" not in arcrole:
                continue
            from_id = arc.get(f"{{{NS_XLINK}}}from", "")
            to_id   = arc.get(f"{{{NS_XLINK}}}to", "")
            # Resolve severity level from locator id
            if "ERROR" in to_id.upper():
                severity_map[from_id] = "ERROR"
            elif "WARNING" in to_id.upper():
                severity_map[from_id] = "WARNING"
            else:
                severity_map[from_id] = "OK"

        # ── Step 3: collect precondition arcs ────────────────────────────────
        # variable-set-precondition: assertion_id → list[precondition_var_id]
        precondition_vars: dict[str, list[str]] = {}
        for arc in root.findall(f".//{{{NS_VAR}}}variableArc"):
            arcrole = arc.get(f"{{{NS_XLINK}}}arcrole", "")
            if "variable-set-precondition" not in arcrole:
                continue
            from_id = arc.get(f"{{{NS_XLINK}}}from", "")
            to_id   = arc.get(f"{{{NS_XLINK}}}to", "")
            precondition_vars.setdefault(from_id, []).append(to_id)

        # ── Step 4: resolve precondition var ids → concept qnames ────────────
        # via variable:variableFilterArc  factVariable → conceptName
        var_to_concept: dict[str, str] = {}
        for arc in root.findall(f".//{{{NS_VAR}}}variableFilterArc"):
            arcrole = arc.get(f"{{{NS_XLINK}}}arcrole", "")
            if "variable-filter" not in arcrole:
                continue
            from_id = arc.get(f"{{{NS_XLINK}}}from", "")  # factVariable id label
            to_id   = arc.get(f"{{{NS_XLINK}}}to", "")    # conceptName id label
            if to_id in concept_filters:
                var_to_concept[from_id] = concept_filters[to_id]

        # ── Step 5: parse variable-set arcs (assertion → factVariable) ───────
        assertion_to_vars: dict[str, list[str]] = {}
        for arc in root.findall(f".//{{{NS_VAR}}}variableArc"):
            arcrole = arc.get(f"{{{NS_XLINK}}}arcrole", "")
            if "variable-set" not in arcrole or "precondition" in arcrole:
                continue
            from_id = arc.get(f"{{{NS_XLINK}}}from", "")
            to_id   = arc.get(f"{{{NS_XLINK}}}to", "")
            assertion_to_vars.setdefault(from_id, []).append(to_id)

        # ── Step 6: collect link role from roleRef ───────────────────────────
        link_role = ""
        role_ref = root.find(f"{{{NS_LINK}}}roleRef")
        if role_ref is None:
            role_ref = root.find(f".//{{{NS_LINK}}}roleRef")
        if role_ref is not None:
            link_role = role_ref.get("roleURI", "")

        # ── Step 7: create AssertionRule for each ea:existenceAssertion ──────
        for ea_el in root.findall(f".//{{{NS_EA}}}existenceAssertion"):
            ea_id   = ea_el.get("id", "")
            ea_lbl  = ea_el.get(f"{{{NS_XLINK}}}label", ea_id)
            severity = severity_map.get(ea_lbl, severity_map.get(ea_id, "WARNING"))

            # Find the concept being asserted (primary variable → concept filter)
            primary_vars = assertion_to_vars.get(ea_lbl, assertion_to_vars.get(ea_id, []))
            concept_qname = ""
            for var_lbl in primary_vars:
                if var_lbl in var_to_concept:
                    concept_qname = var_to_concept[var_lbl]
                    break

            # Precondition concepts
            prec_var_lbls = precondition_vars.get(ea_lbl, precondition_vars.get(ea_id, []))
            prec_qnames: list[str] = []
            for pv in prec_var_lbls:
                pq = var_to_concept.get(pv)
                if pq:
                    prec_qnames.append(pq)

            if not concept_qname:
                # Try to infer from the assertion id naming convention
                # e.g. "existenceAssertion_EntityInformation_PrtExistOnce3_LegalEntityName"
                parts = ea_id.rsplit("_", 1)
                if len(parts) == 2:
                    local_guess = parts[-1]
                    # Find matching element in concept_filters by local name
                    for cf_qn in concept_filters.values():
                        if cf_qn.split(":")[-1] == local_guess:
                            concept_qname = cf_qn
                            break

            if not concept_qname:
                continue

            rule = AssertionRule(
                id=ea_id,
                assertion_type="existence",
                severity=severity,
                concept_qname=concept_qname,
                precondition_qnames=prec_qnames,
                link_role=link_role,
                source_file=source_name,
            )
            self._assertions[ea_id] = rule

        # ── Step 8: parse va:valueAssertion (always conditional) ─────────────
        for va_el in root.findall(f".//{{{NS_VA}}}valueAssertion"):
            va_id   = va_el.get("id", "")
            va_lbl  = va_el.get(f"{{{NS_XLINK}}}label", va_id)
            test    = va_el.get("test", "")
            severity = severity_map.get(va_lbl, severity_map.get(va_id, "WARNING"))

            # Concepts referenced in this value assertion
            primary_vars = assertion_to_vars.get(va_lbl, assertion_to_vars.get(va_id, []))
            for var_lbl in primary_vars:
                concept_qname = var_to_concept.get(var_lbl, "")
                if not concept_qname:
                    continue
                rule = AssertionRule(
                    id=f"{va_id}:{var_lbl}",
                    assertion_type="value",
                    severity=severity,
                    concept_qname=concept_qname,
                    test_expression=test,
                    link_role=link_role,
                    source_file=source_name,
                )
                self._assertions[rule.id] = rule

        # Also follow loc hrefs in formula linkbases to load referenced XSDs
        for loc in root.findall(f".//{{{NS_LINK}}}loc"):
            href = loc.get(f"{{{NS_XLINK}}}href", "")
            url, _, _ = href.rpartition("#")
            if url:
                resolved = self.catalog.resolve_href(url, filepath)
                self._parse_file(resolved, entry_key)

    # ─────────────────────────────────────────────────────────────────────────
    # Build ConceptMetadata objects from all collected data
    # ─────────────────────────────────────────────────────────────────────────

    def _build_concepts(self, entry_key: str | None) -> dict[str, ConceptMetadata]:
        """
        Combine XSD elements, labels, assertions, and presentation into
        ConceptMetadata objects.  If entry_key is given, only return concepts
        that belong to that entry point.
        """
        # Build assertion lookup: qname → best AssertionRule
        qname_to_rule: dict[str, AssertionRule] = {}
        for rule in self._assertions.values():
            qn = rule.concept_qname
            existing = qname_to_rule.get(qn)
            if existing is None:
                qname_to_rule[qn] = rule
            else:
                # Prefer mandatory (ERROR, no precondition) over conditional
                if rule.derived_status == "mandatory" and existing.derived_status != "mandatory":
                    qname_to_rule[qn] = rule

        concepts: dict[str, ConceptMetadata] = {}

        for qname, el in self._elements.items():
            # Filter by entry point if requested
            ep_list = self._concept_entry_points.get(qname, [])
            if entry_key and entry_key not in ep_list:
                continue

            prefix, _, name = qname.partition(":")
            ns_uri = self._nsmap.get(prefix, "")

            # XSD attributes
            data_type = el.get("type", "xbrli:stringItemType")
            period_type = el.get("{http://www.xbrl.org/2003/instance}periodType",
                          el.get("periodType", "duration"))
            balance = el.get("{http://www.xbrl.org/2003/instance}balance",
                      el.get("balance", None))
            abstract = el.get("abstract", "false").lower() == "true"
            nillable = el.get("nillable", "true").lower() == "true"
            sub_group = el.get("substitutionGroup", "")

            # Labels
            lbl_store = self._labels.get(qname, {})
            label_nl         = lbl_store.get("nl:label") or lbl_store.get("nl:terse")
            label_en         = lbl_store.get("en:label") or lbl_store.get("en:terse")
            label_nl_verbose = lbl_store.get("nl:verbose")
            label_nl_terse   = lbl_store.get("nl:terse")
            label_nl_total   = lbl_store.get("nl:total")
            doc_nl           = lbl_store.get("nl:doc")

            # Presentation
            pres = self._presentation.get(qname, {})
            parent_q  = pres.get("parent_qname")
            pres_order = pres.get("order", 0.0)
            link_role  = pres.get("link_role")
            depth      = pres.get("depth", 0)

            # Calculation
            calc = self._calculation.get(qname, {})

            # Status from assertions
            rule = qname_to_rule.get(qname)
            status    = rule.derived_status if rule else "optional"
            rule_id   = rule.id if rule else None
            rule_src  = rule.source_file if rule else None
            prec_q    = rule.precondition_qnames[0] if (rule and rule.precondition_qnames) else None

            concept = ConceptMetadata(
                qname=qname,
                name=name,
                namespace=ns_uri,
                prefix=prefix,
                data_type=data_type,
                period_type=period_type,
                balance=balance,
                abstract=abstract,
                nillable=nillable,
                substitution_group=sub_group,
                label_nl=label_nl,
                label_en=label_en,
                label_nl_verbose=label_nl_verbose,
                label_nl_terse=label_nl_terse,
                label_nl_total=label_nl_total,
                documentation_nl=doc_nl,
                parent_qname=parent_q,
                presentation_order=float(pres_order),
                depth=depth,
                link_role=link_role,
                calculation_parents=calc,
                status=status,
                rule_id=rule_id,
                rule_source=rule_src,
                precondition_qname=prec_q,
                taxonomy_version=self.taxonomy_version,
                entry_points=list(ep_list),
            )
            concepts[qname] = concept

        return concepts

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _prefix_for_ns(self, uri: str) -> str | None:
        for pfx, ns in self._nsmap.items():
            if ns == uri:
                return pfx
        return None
