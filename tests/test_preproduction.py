from hashlib import sha256
import io
import json
from pathlib import Path
import zipfile

import pytest

from arelle_validator import capabilities, diagnose, validate_report
from taxonomy_package import extract_verified
from submission import readiness, create_handoff
from package import create_report_package
from tests.test_regressions import snapshot, registry, document, api
from service import FilingService


def test_real_arelle_rejects_bad_xml_and_plain_html():
    pytest.importorskip("arelle")
    result = diagnose(b"<bad")
    assert not result["technical_valid"]
    assert any(m["code"] == "xmlSchema:syntax" for m in result["messages"])
    assert not diagnose(b'<html xmlns="http://www.w3.org/1999/xhtml"/>')["technical_valid"]


def test_missing_2026_profile_cannot_authorize_filing():
    pytest.importorskip("arelle")
    assert "NT21" not in capabilities()["profiles"]
    result = diagnose(b"unused", profile="NT21")
    assert result["messages"][0]["code"] == "PROFILE_UNAVAILABLE"
    assert not result["suitable_for_filing"]
    assert validate_report("<bad", None, None)


@pytest.mark.parametrize("name", ["../outside", "/absolute", "folder/../../outside", "a\\bad"])
def test_archive_rejects_unsafe_paths(tmp_path, name):
    path = tmp_path / "package.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "unsafe")
    with pytest.raises(ValueError, match="Unsafe"):
        extract_verified(path, sha256(path.read_bytes()).hexdigest(), tmp_path / "out")
    assert not list((tmp_path / "out").iterdir())


def test_archive_checks_hash_and_preserves_package_root(tmp_path):
    path = tmp_path / "package.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("release/META-INF/taxonomyPackage.xml", "<taxonomyPackage/>")
        archive.writestr("release/entry.xsd", "<schema/>")
    with pytest.raises(ValueError, match="checksum"):
        extract_verified(path, "0" * 64, tmp_path / "out")
    root = extract_verified(path, sha256(path.read_bytes()).hexdigest(), tmp_path / "out")
    assert (root / "entry.xsd").read_text() == "<schema/>"


def test_handoff_identifies_exact_payload_and_does_not_submit():
    snap = snapshot()
    snap.freeze()
    reg = registry()
    payload = FilingService(reg, lambda *_: []).validate_and_package(snap, document())
    assert payload == FilingService(reg, lambda *_: []).validate_and_package(snap, document())
    with zipfile.ZipFile(io.BytesIO(create_handoff(payload, snap, reg.get('test')))) as archive:
        evidence = json.loads(archive.read("handoff.json"))
        assert sha256(archive.read("report.zip")).hexdigest() == evidence["payload_sha256"]
        assert not evidence["submitted"]
    assert readiness()["production_enabled"] is False
    assert readiness()["direct"]["connected"] is False


def test_api_preparation_routes_and_export_gate(api):
    client, main = api
    result = client.get('/api/submission/readiness')
    assert result.status_code == 200
    assert result.json()['production_enabled'] is False
    assert client.post('/api/snapshot/absent/independent-validation').status_code == 404
    snap = snapshot()
    main.store.add(snap)
    main.store.add_document(document())
    assert client.post('/api/snapshot/test-filing/provider-handoff').status_code == 422


def test_verified_archive_is_enriched_and_beta_cannot_export(api, tmp_path, monkeypatch):
    _, main = api
    monkeypatch.setattr(main, '_TAXONOMY_DIR', tmp_path)
    path = tmp_path / 'release.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('release/META-INF/taxonomyPackage.xml', '<taxonomyPackage/>')
        archive.writestr('release/ep.xsd', '<schema/>')
    manifest = {'id': 'beta', 'status': 'final', 'version': '20261209.b',
                'package_file': path.name, 'sha256': sha256(path.read_bytes()).hexdigest(),
                'entry_points': {'ep': 'ep.xsd'}}
    (tmp_path / 'beta.json').write_text(json.dumps(manifest))
    main._load_verified_taxonomies()
    release = main.taxonomy_registry.get('beta')
    assert release.status == 'beta'
    assert not release.package_verified
    assert Path(release.package_path, 'ep.xsd').exists()
    assert not release.complete_entry_points
