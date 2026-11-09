from datetime import date
from decimal import Decimal
import pytest
from models import Context, Fact, FilingSnapshot, SourceRef, Unit
from tests.test_regressions import api, snapshot, document


def test_list_companies_and_yearly_grouping(api):
    client, main = api
    s1 = snapshot()  # KVK 12345678, 2024
    s1.filing_id = "f-2024"
    s1.period_start = date(2024, 1, 1)
    s1.period_end = date(2024, 12, 31)
    s1.entity_name = "Alpha B.V."
    main.store.add(s1)

    # Add second year for Alpha B.V.
    s2 = snapshot()
    s2.filing_id = "f-2025"
    s2.period_start = date(2025, 1, 1)
    s2.period_end = date(2025, 12, 31)
    s2.entity_name = "Alpha B.V."
    main.store.add(s2)

    # Add another company Beta N.V.
    s3 = snapshot()
    s3.filing_id = "f-beta-2025"
    s3.kvk_number = "87654321"
    s3.period_start = date(2025, 1, 1)
    s3.period_end = date(2025, 12, 31)
    s3.entity_name = "Beta N.V."
    main.store.add(s3)

    resp = client.get("/api/companies")
    assert resp.status_code == 200
    companies = resp.json()["companies"]
    assert len(companies) == 2

    alpha = next(c for c in companies if c["kvk_number"] == "12345678")
    assert alpha["entity_name"] == "Alpha B.V."
    assert alpha["total_filings"] == 2
    assert alpha["latest_year"] == 2025
    assert len(alpha["filings"]) == 2
    assert alpha["filings"][0]["year"] == 2025
    assert alpha["filings"][1]["year"] == 2024

    beta = next(c for c in companies if c["kvk_number"] == "87654321")
    assert beta["entity_name"] == "Beta N.V."
    assert beta["total_filings"] == 1


def test_yearly_rollover_workflow(api):
    client, main = api
    s = snapshot()
    s.filing_id = "source-2024"
    s.kvk_number = "11223344"
    s.entity_name = "Rollover Test B.V."
    s.period_start = date(2024, 1, 1)
    s.period_end = date(2024, 12, 31)
    s.profile_id = "2024-nlgaap-klein-general-standalone"
    s.units = [Unit("eur", "iso4217:EUR")]
    s.contexts = [
        Context("ctx_current", "http://www.kvk.nl/kvk-id", "11223344", start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)),
        Context("ctx_instant_end", "http://www.kvk.nl/kvk-id", "11223344", instant=date(2024, 12, 31))
    ]
    s.facts = [
        Fact("f1", "kvk-i:Assets", "ctx_instant_end", Decimal("50000"), "numeric",
             SourceRef(s.document_sha256, "row 1", "50000", "accountant"), "eur", -3, scale=3)
    ]
    main.store.add(s)

    # Perform rollover into 2025
    resp = client.post("/api/company/rollover", json={
        "source_filing_id": "source-2024",
        "target_year": 2025,
        "carry_over_comparatives": True
    })
    assert resp.status_code == 201
    new_filing = resp.json()
    assert new_filing["kvk_number"] == "11223344"
    assert new_filing["entity_name"] == "Rollover Test B.V."
    assert new_filing["period_start"] == "2025-01-01"
    assert new_filing["period_end"] == "2025-12-31"
    assert new_filing["state"] == "draft"

    # Contexts must be advanced
    ctx_ids = {c["id"] for c in new_filing["contexts"]}
    assert "ctx_current" in ctx_ids
    assert "ctx_instant_end" in ctx_ids
    assert "ctx_instant_prior" in ctx_ids

    # Carried over fact becomes prior-year comparative
    assert len(new_filing["facts"]) == 1
    rolled_fact = new_filing["facts"][0]
    assert rolled_fact["context_id"] == "ctx_instant_prior"
    assert rolled_fact["value"] == "50000"
    assert rolled_fact["scale"] == 3


def test_delete_draft_filing(api):
    client, main = api
    s = snapshot()
    s.filing_id = "draft-to-delete"
    s.kvk_number = "99887766"
    s.entity_name = "Deletable B.V."
    main.store.add(s)

    # Verify present
    resp = client.get("/api/companies")
    assert any(c["kvk_number"] == "99887766" for c in resp.json()["companies"])

    # Delete the draft
    del_resp = client.delete(f"/api/filings/{s.filing_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True
    assert del_resp.json()["filing_id"] == s.filing_id

    # Verify removed from companies list
    resp2 = client.get("/api/companies")
    assert not any(c["kvk_number"] == "99887766" for c in resp2.json()["companies"])

    # Attempting to delete again returns 404
    del_resp2 = client.delete(f"/api/filings/{s.filing_id}")
    assert del_resp2.status_code == 404


def test_rollover_2025_to_2026_with_nt21_and_template_memories(api):
    client, main = api
    s25 = snapshot()
    s25.filing_id = "f-2025-approved"
    s25.kvk_number = "34254022"
    s25.entity_name = "Test Company 34254022 B.V."
    s25.period_start = date(2025, 1, 1)
    s25.period_end = date(2025, 12, 31)
    s25.profile_id = "2025-nlgaap-klein-general-standalone"
    s25.taxonomy_id = "KVK_IXBRL_2025"
    s25.entry_point_key = "nlgaap"
    s25.units = [Unit("eur", "iso4217:EUR")]
    s25.contexts = [
        Context("ctx_current", "http://www.kvk.nl/kvk-id", "34254022", start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)),
        Context("ctx_instant_end", "http://www.kvk.nl/kvk-id", "34254022", instant=date(2025, 12, 31))
    ]
    s25.facts = [
        Fact("f-bs", "kvk-i:Assets", "ctx_instant_end", Decimal("75000"), "numeric",
             SourceRef(s25.document_sha256, "Balance Sheet", "75000", "accountant"), "eur", -3, scale=3),
        Fact("f-pl", "kvk-i:NetTurnover", "ctx_current", Decimal("120000"), "numeric",
             SourceRef(s25.document_sha256, "P&L", "120000", "accountant"), "eur", -3, scale=3)
    ]
    main.store.add(s25)

    # Rollover to FY 2026
    resp = client.post("/api/company/rollover", json={
        "source_filing_id": "f-2025-approved",
        "target_year": 2026,
        "carry_over_comparatives": True
    })
    assert resp.status_code == 201
    f26 = resp.json()

    # 2026 profile should use NT21 taxonomy rules and 2026 profile
    assert f26["profile_id"] == "2026-nlgaap-klein-general-standalone"
    assert f26["taxonomy_id"] == "NT21_KVK_20261209_b"
    assert f26["entry_point_key"] == "klein_nlgaap"
    assert f26["period_start"] == "2026-01-01"
    assert f26["period_end"] == "2026-12-31"
    assert f26["rollover_from_filing_id"] == "f-2025-approved"
    assert "kvk-i:Assets" in f26["template_concepts"]
    assert "kvk-i:NetTurnover" in f26["template_concepts"]

    # Both balance sheet and P&L comparatives carried over
    assert len(f26["facts"]) == 2
    facts_by_ctx = {f["context_id"]: f for f in f26["facts"]}
    assert "ctx_instant_prior" in facts_by_ctx
    assert facts_by_ctx["ctx_instant_prior"]["value"] == "75000"
    assert "ctx_prior" in facts_by_ctx
    assert facts_by_ctx["ctx_prior"]["value"] == "120000"

    # User can attach new 2026 document to the draft filing
    new_doc = document()
    main.store.add_document(new_doc)
    doc_resp = client.put(f"/api/snapshot/{f26['filing_id']}/document", json={
        "document_sha256": new_doc.sha256
    })
    assert doc_resp.status_code == 200
    assert doc_resp.json()["document_sha256"] == new_doc.sha256

