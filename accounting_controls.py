"""Reviewable accounting checks using canonical values and semantic contexts.

Equation bindings must be supplied by a qualified accounting ruleset, never
inferred from similar labels. No generic profit/cash-flow formula is asserted.
"""
from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json


def context_key(context):
    return (context.entity_scheme, context.entity_identifier, context.instant,
            context.start_date, context.end_date,
            tuple(sorted((d.axis, d.member) for d in context.dimensions)))


def fact_groups(snapshot):
    contexts = {c.id: c for c in snapshot.contexts}
    units = {u.id: u.measure for u in snapshot.units}
    groups = defaultdict(list)
    for fact in snapshot.facts:
        if fact.context_id in contexts:
            groups[(fact.qname, context_key(contexts[fact.context_id]),
                    units.get(fact.unit_id), fact.kind)].append(fact)
    return groups


def duplicate_issues(snapshot):
    from validator import ValidationIssue
    issues = []
    for (qname, *_), facts in fact_groups(snapshot).items():
        if len(facts) > 1:
            conflicting = len({(f.nil, str(f.value)) for f in facts}) > 1
            issues.append(ValidationIssue(
                "ACCOUNTING_CONFLICT" if conflicting else "ACCOUNTING_DUPLICATE",
                "Same fact aspects reported more than once: " + ", ".join(f.id for f in facts),
                qname, "error" if conflicting else "warning"))
    return issues


def reconcile(snapshot, rule_id, terms):
    """Evaluate explicitly bound (fact_id, signed weight) terms summing to zero.

    Returns evidence; missing or incompatible facts never yield a pass. Cross-
    period roll-forwards need a separately qualified rule implementation.
    """
    facts = {f.id: f for f in snapshot.facts}
    contexts = {c.id: c for c in snapshot.contexts}
    units = {u.id: u.measure for u in snapshot.units}
    result = {"rule_id": rule_id, "status": "incomplete", "inputs": []}
    selected = []
    if len(terms) < 2 or len({t[0] for t in terms}) != len(terms):
        return result
    for fact_id, weight in terms:
        f = facts.get(fact_id)
        weight = Decimal(str(weight))
        if (not f or f.nil or f.kind != "numeric" or f.context_id not in contexts
                or f.unit_id not in units or not weight.is_finite() or not weight):
            return result
        selected.append((f, weight))
        result["inputs"].append({"fact_id": f.id, "value": str(f.value), "weight": str(weight),
                                 "decimals": f.decimals, "context_id": f.context_id})
    if len({(context_key(contexts[f.context_id]), units[f.unit_id]) for f, _ in selected}) != 1:
        result["reason"] = "Incompatible periods, dimensions, entities or units."
        return result
    difference = sum((f.value * w for f, w in selected), Decimal(0))
    tolerance = sum((Decimal('0.5').scaleb(-f.decimals) * abs(w) for f, w in selected), Decimal(0))
    result.update(difference=str(difference), tolerance=str(tolerance),
                  status="pass" if difference == 0 else "rounding_review" if abs(difference) <= tolerance else "error")
    return result


def compare_prior(current, prior):
    """Compare overlapping aspects; changes require a restatement explanation."""
    old = fact_groups(prior)
    changes = []
    for key, facts in fact_groups(current).items():
        if key in old and {(f.nil, str(f.value)) for f in facts} != {(f.nil, str(f.value)) for f in old[key]}:
            changes.append({"concept": key[0], "status": "review_required",
                            "current_fact_ids": [f.id for f in facts],
                            "prior_fact_ids": [f.id for f in old[key]],
                            "reason": "Changed comparative; assess restatement or correction."})
    return changes


def taxonomy_reconciliations(snapshot, taxonomy):
    """Calculation-network evidence, including explicitly incomplete checks."""
    if not hasattr(taxonomy, "get_concepts_for_ep"):
        return []
    groups = fact_groups(snapshot)
    networks = {}
    for concept in taxonomy.get_concepts_for_ep(snapshot.entry_point_key):
        for arc in concept.calc_relationships:
            networks.setdefault((arc.link_role, arc.parent_qname), {})[arc.child_qname] = Decimal(str(arc.weight))
    records = []
    for (role, parent), children in networks.items():
        for (qname, context, unit, kind), parent_facts in groups.items():
            if qname != parent or kind != "numeric":
                continue
            rule_id = role + "#" + parent
            matches = [groups.get((child, context, unit, kind), []) for child in children]
            if len(parent_facts) != 1 or any(len(fs) != 1 for fs in matches):
                records.append({"rule_id": rule_id, "status": "incomplete",
                                "reason": "Missing or duplicate calculation inputs.",
                                "parent_fact_ids": [f.id for f in parent_facts]})
                continue
            terms = [(parent_facts[0].id, 1)] + [(fs[0].id, -weight) for fs, weight in zip(matches, children.values())]
            records.append(reconcile(snapshot, rule_id, terms))
    return records


def issue_id(issue):
    return sha256(json.dumps(asdict(issue), sort_keys=True).encode()).hexdigest()


def undisposed_warnings(snapshot, issues):
    approved = {d.get("issue_id") for d in snapshot.warning_dispositions
                if d.get("content_digest") == snapshot.review_digest()
                and str(d.get("reason", "")).strip() and d.get("reviewer") and d.get("disposed_at")}
    return [i for i in issues if i.severity == "warning" and issue_id(i) not in approved]
