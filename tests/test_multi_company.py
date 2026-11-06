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
