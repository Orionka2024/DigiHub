from datetime import date
from decimal import Decimal
import hashlib
import io
import json
import unittest
import zipfile

from models import Context, Fact, FilingSnapshot, SourceRef, Unit
from registry import TaggingRequirement, TaxonomyRegistry, TaxonomyRelease
from service import ExportBlocked, FilingService
from docx_extract import ExtractedDocument, SourceNode


class FilingCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = TaxonomyRegistry()
        self.registry.register(TaxonomyRelease(
            id="TEST_KVK_2026", status="final",
            entry_points={"groot": "https://example.test/kvk-groot.xsd"},
            namespaces={"kvk": "https://example.test/kvk"}, sha256="a" * 64, package_verified=True,
            requirements=(
                TaggingRequirement("balance-sheet", None, "balance sheet"),
                TaggingRequirement("revenue", "kvk:Revenue", None),
                TaggingRequirement("accountant-report", None, "accountant report", conditional=True),
            ),
        ))

    def snapshot(self) -> FilingSnapshot:
        digest = hashlib.sha256(b"source").hexdigest()
        return FilingSnapshot(
            filing_id="f-1", entity_name="Example Finance B.V.", kvk_number="34254022",
            period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
            taxonomy_id="TEST_KVK_2026", entry_point_key="groot", document_sha256=digest,
            contexts=[Context("duration", "http://www.kvk.nl/kvk-id", "34254022", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))],
            units=[Unit("USD", "iso4217:USD")],
            facts=[Fact("revenue", "kvk:Revenue", "duration", Decimal("125400000"), "numeric", SourceRef(digest, "Table 4, row 5", "125,400", reviewer="Test Accountant"), "USD", -3)],
            report_sections={"balance sheet", "accountant report"},
            reviewed_requirement_ids={"accountant-report"},
        )

    def test_export_is_blocked_until_frozen(self) -> None:
        with self.assertRaises(ExportBlocked):
            FilingService(self.registry).validate_and_package(self.snapshot())

    def test_packages_selected_kvk_entrypoint(self) -> None:
        snapshot = self.snapshot()
        snapshot.freeze()
        # This injected validator exercises orchestration; it is not a conformance test.
        document = ExtractedDocument(snapshot.document_sha256,
            (SourceNode("p1", "paragraph", "Table 4, row 5", None, "125,400"),), (), (), ())
        package = FilingService(self.registry, external_validator=lambda *_: []).validate_and_package(snapshot, document)
        self.assertEqual(snapshot.state.value, "validated")
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            manifest = json.loads(archive.read("34254022-2026/META-INF/reportPackage.json"))
            self.assertEqual(manifest["documentInfo"]["documentType"], "https://xbrl.org/report-package/2023")
            ixbrl = archive.read("34254022-2026/reports/34254022-2026.xhtml")
            self.assertIn(b"iso4217:USD", ixbrl)
            self.assertIn(b"https://example.test/kvk-groot.xsd", ixbrl)

    def test_rejects_wrong_provenance(self) -> None:
        snapshot = self.snapshot()
        snapshot.facts[0] = Fact("revenue", "kvk:Revenue", "duration", Decimal("1"), "numeric", SourceRef("b" * 64, "T", "1"), "USD", 0)
        snapshot.freeze()
        with self.assertRaisesRegex(ExportBlocked, "PROVENANCE"):
            FilingService(self.registry).validate_and_package(snapshot)

    def test_rejects_unreviewed_conditional_requirement(self) -> None:
        snapshot = self.snapshot()
        snapshot.reviewed_requirement_ids.clear()
        snapshot.freeze()
        with self.assertRaisesRegex(ExportBlocked, "CONDITIONAL_REVIEW"):
            FilingService(self.registry).validate_and_package(snapshot)

    def test_rejects_missing_mandatory_tag(self) -> None:
        snapshot = self.snapshot()
        snapshot.facts.clear()
        snapshot.freeze()
        with self.assertRaisesRegex(ExportBlocked, "MANDATORY_TAG"):
            FilingService(self.registry).validate_and_package(snapshot)


if __name__ == "__main__":
    unittest.main()
