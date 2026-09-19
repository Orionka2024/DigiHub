import pytest
from datetime import date
from KVK_v2.models import FilingSnapshot, Fact, SourceRef
from KVK_v2.validator import validate_snapshot
from KVK_v2.registry import EnrichedTaxonomyRelease
from KVK_v2.taxonomy.rules import RulesEngine, ValidationRule, MandatoryStatus, RuleType

@pytest.fixture
def dummy_taxonomy():
    engine = RulesEngine()
    engine.add_rule(ValidationRule(
        rule_id="r1",
        rule_type=RuleType.EXISTENCE,
        status=MandatoryStatus.MANDATORY,
        concept_qname="kvk:MandatoryConcept",
        entry_points=("test_ep",)
    ))
    engine.add_rule(ValidationRule(
        rule_id="r2",
        rule_type=RuleType.EXISTENCE,
        status=MandatoryStatus.CONDITIONAL,
        concept_qname="kvk:ConditionalConcept",
        condition_nl="Indien van toepassing",
        entry_points=("test_ep",)
    ))
    
    release = EnrichedTaxonomyRelease(
        id="test_tax", status="final", version="1.0", name="Test Tax",
        authority="Test", publication_date="2026-01-01", reporting_year=2026,
        reporting_date="2026-12-31", sha256="test", package_verified=True
    )
    release.rules_engine = engine
    return release

@pytest.fixture
def dummy_snapshot():
    snap = FilingSnapshot(
        filing_id="1", entity_name="Test BV", kvk_number="12345678",
        period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        taxonomy_id="test_tax", entry_point_key="test_ep", document_sha256="a" * 64
    )
    snap.is_final = True
    snap.signatory_name = "Signatory"
    snap.approval_date = date(2026, 12, 31)
    # Add dummy context and fact so SBR tests don't fail immediately
    from KVK_v2.models import Context
    snap.contexts.append(Context("ctx1", "http://www.kvk.nl/kvk-id", "12345678", instant=date(2026, 12, 31)))
    snap.facts.append(Fact("f1", "kvk:OtherConcept", "ctx1", "test", "text", SourceRef("a" * 64, "body paragraph 1", "test", "Reviewer")))
    return snap

def test_missing_mandatory_fact(dummy_snapshot, dummy_taxonomy):
    issues = validate_snapshot(dummy_snapshot, dummy_taxonomy)
    req1_issues = [i for i in issues if i.rule_ref == "r1"]
    assert len(req1_issues) == 1
    assert req1_issues[0].severity == "error"
    assert req1_issues[0].code == "REQ-001"

def test_conditional_fact_requires_review(dummy_snapshot, dummy_taxonomy):
    issues = validate_snapshot(dummy_snapshot, dummy_taxonomy)
    req2_issues = [i for i in issues if i.rule_ref == "r2"]
    assert len(req2_issues) == 1
    assert req2_issues[0].severity == "error"
    assert req2_issues[0].code == "REQ-002"

def test_conditional_fact_reviewed(dummy_snapshot, dummy_taxonomy):
    dummy_snapshot.reviewed_requirement_ids.add("r2")
    issues = validate_snapshot(dummy_snapshot, dummy_taxonomy)
    req2_issues = [i for i in issues if i.rule_ref == "r2"]
    assert len(req2_issues) == 0

def test_present_mandatory_fact(dummy_snapshot, dummy_taxonomy):
    dummy_snapshot.facts.append(Fact("f2", "kvk:MandatoryConcept", "ctx1", "test", "text", SourceRef("a" * 64, "body paragraph 1", "test", "Reviewer")))
    issues = validate_snapshot(dummy_snapshot, dummy_taxonomy)
    req1_issues = [i for i in issues if i.rule_ref == "r1"]
    assert len(req1_issues) == 0
