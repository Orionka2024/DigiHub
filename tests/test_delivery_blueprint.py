from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
import zipfile

import pytest
from lxml import etree
from docx import Document

from accounting_controls import duplicate_issues, reconcile, issue_id, undisposed_warnings, compare_prior
from app.store import _snapshot_from_dict, _snapshot_to_dict
from docx_extract import extract_docx, ExtractedDocument, SourceNode
from generator import generate_ixbrl
from models import Fact, SourceRef, Unit, Dimension
from reporting_profile import get_profile, check_profile, RULES_2025
from service import FilingService, ExportBlocked
from submission import create_audit_bundle
from tests.test_regressions import snapshot, registry, document, api
from validator import ValidationIssue


def numeric(value='12000', source='12', scale=3, locale='en'):
    s = snapshot()
    s.units = [Unit('eur', 'iso4217:EUR')]
    s.facts = [Fact('amount', 't:Assets', 'c', Decimal(value), 'numeric',
                    SourceRef(s.document_sha256, 'body paragraph 1', source, 'accountant'),
                    'eur', -3, scale=scale, sign='-' if Decimal(value) < 0 else None,
                    number_format=locale)]
    doc = ExtractedDocument(s.document_sha256, (SourceNode('p1', 'paragraph', 'body paragraph 1', None, source),), (), (), ())
    return s, doc


@pytest.mark.parametrize('value,text,scale,locale', [('12000','12',3,'en'), ('-1234.50','(1.234,50)',0,'nl'), ('1.25','1,25',0,'nl')])
def test_inline_source_and_value_alignment(value, text, scale, locale):
    s, doc = numeric(value, text, scale, locale)
    root = etree.fromstring(generate_ixbrl(s, {'t':'urn:test'}, entry_point='urn:ep', document=doc).encode())
    body = root.xpath('//*[@id="document-body"]')[0]
    assert ''.join(body.itertext()) == text
    fact = body.xpath('.//*[local-name()="nonFraction"]')[0]
    assert int(fact.get('scale')) == scale
    assert (fact.get('sign') == '-') == (Decimal(value) < 0)
    assert 'Reviewed facts' not in ''.join(root.itertext())


def test_source_value_mismatch_is_not_silently_replaced():
    s, doc = numeric('13000')
    with pytest.raises(ValueError, match='INLINE_VALUE'):
        generate_ixbrl(s, document=doc)


def test_equivalent_context_ids_cannot_hide_conflicts():
    s, _ = numeric()
    s.contexts.append(replace(s.contexts[0], id='other'))
    s.facts.append(replace(s.facts[0], id='different', context_id='other', value=Decimal(999)))
    assert duplicate_issues(s)[0].code == 'ACCOUNTING_CONFLICT'
    s.facts[1] = replace(s.facts[1], value=s.facts[0].value)
    assert duplicate_issues(s)[0].severity == 'warning'


def test_dimension_container_and_unique_axes():
    s, _ = numeric()
    s.contexts[0] = replace(s.contexts[0], dimensions=(Dimension('t:Axis','t:Member'),))
    xml = generate_ixbrl(s, {'t':'urn:test'}, entry_point='urn:ep')
    assert '<xbrli:scenario>' in xml and '<xbrli:segment>' not in xml
    with pytest.raises(ValueError, match='repeat'):
        replace(s.contexts[0], dimensions=(Dimension('t:Axis','t:A'),Dimension('t:Axis','t:B')))


def test_reconciliation_does_not_cross_units_or_periods():
    s, _ = numeric()
    s.facts.append(replace(s.facts[0], id='equity', qname='t:Equity', value=Decimal(5000)))
    s.facts.append(replace(s.facts[0], id='liabilities', qname='t:Liabilities', value=Decimal(7000)))
    terms = [('amount',1),('equity',-1),('liabilities',-1)]
    assert reconcile(s,'reviewed-equation',terms)['status'] == 'pass'
    s.contexts.append(replace(s.contexts[0], id='prior', instant=date(2025,12,31)))
    s.facts[1] = replace(s.facts[1], context_id='prior')
    assert reconcile(s,'reviewed-equation',terms)['status'] == 'incomplete'
    assert reconcile(s,'reviewed-equation',[('missing',1),('equity',-1)])['status'] == 'incomplete'


def test_changed_comparative_requires_review_not_forced_equality():
    s, _ = numeric()
    prior = replace(s, facts=[replace(s.facts[0], value=Decimal(11000))])
    assert compare_prior(s,prior)[0]['status'] == 'review_required'


def test_disposition_bound_to_content_and_persisted():
    s, _ = numeric()
    issue = ValidationIssue('ROUND','Rounding difference',severity='warning')
    s.warning_dispositions = [{'issue_id':issue_id(issue),'content_digest':s.review_digest(),
                              'reason':'Reviewed rounding against original statements',
                              'reviewer':'accountant','disposed_at':'2026-11-06T10:00:00Z'}]
    assert not undisposed_warnings(s,[issue])
    restored = _snapshot_from_dict(_snapshot_to_dict(s))
    assert restored.facts[0].scale == 3
    assert not undisposed_warnings(restored,[issue])
    restored.facts[0] = replace(restored.facts[0], value=Decimal(13000))
    assert undisposed_warnings(restored,[issue])


def test_profile_policy_does_not_enable_unsupported_years():
    assert get_profile('2025-nlgaap-micro-general-standalone').qualification == 'candidate'
    with pytest.raises(ValueError, match='Unsupported'):
        get_profile('2024-nlgaap-micro-general-standalone')
    with pytest.raises(ValueError, match='Unsupported'):
        get_profile('2025-ifrs-micro-general-standalone')


def test_unsupported_word_objects_are_reported():
    original = BytesIO()
    doc = Document(); doc.add_paragraph('Source'); doc.save(original)
    output = BytesIO()
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(output,'w') as dest:
        for n in src.namelist(): dest.writestr(n,src.read(n))
        dest.writestr('word/embeddings/object.bin', b'not rendered')
    assert any('embedded objects' in w for w in extract_docx(output.getvalue()).warnings)


def test_audit_bundle_hashes_and_evidence_binding():
    s = snapshot(); s.freeze()
    reg = registry(); doc = document()
    payload = FilingService(reg, lambda *_: []).validate_and_package(s,doc)
    evidence = {'sha256':sha256(payload).hexdigest(),'technical_valid':True,'engine':{'version':'test-only'}}
    bundle = create_audit_bundle(payload,s,reg.get('test'),document=doc,validation_results=evidence,change_history=[])
    with zipfile.ZipFile(BytesIO(bundle)) as z:
        manifest = json.loads(z.read('manifest.json'))
        assert not manifest['submitted'] and manifest['digital_signatures'] == []
        assert all(sha256(z.read(n)).hexdigest() == digest for n,digest in manifest['files'].items())
    with pytest.raises(ValueError, match='exact report-package'):
        create_audit_bundle(payload,s,reg.get('test'),document=doc,validation_results={**evidence,'sha256':'0'*64},change_history=[])


def test_api_warning_identity_and_error_waiver_gate(api):
    client, main = api
    s = snapshot(); s.is_final=False
    main.store.add(s)
    issues = client.get('/api/snapshot/test-filing/accounting-review').json()['issues']
    warning = next(i for i in issues if i['code']=='SBR-001')
    result = client.post('/api/snapshot/test-filing/warning-dispositions', json={
        'issue_id':warning['issue_id'],'reason':'This is the draft for external auditor review', 'reviewer':'spoofed'})
    assert result.status_code == 200
    assert result.json()['reviewer'] == 'reviewer@example.test'
    assert client.post('/api/snapshot/test-filing/warning-dispositions',json={'issue_id':'invented','reason':'Please ignore all errors'}).status_code == 422


def test_assertion_telemetry_never_waives_unsatisfied_or_unknown_results():
    from validation_evidence_plugin import summarize
    assert summarize([{'balance': (3,0,0,0,0)}])['errors'] == []
    assert summarize([{'balance': (2,1,0,0,0)}])['errors']
    assert summarize(['xmlSchema:error'])['errors']
    assert summarize([{'unexpected': [0,0]}])['errors']


def test_official_suite_indexes_drive_expectations():
    from conformance import cases
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('suite/tests/rule/index.xml', '''<testcase xmlns="http://xbrl.org/2008/conformance"><automatable>true</automatable><variation id="case"><data><taxonomyPackage readMeFirst="true">bad.xbri</taxonomyPackage></data><result><error>specificError</error></result></variation></testcase>''')
    with zipfile.ZipFile(stream) as z:
        case = cases(z)[0]
        assert case['expected_errors'] == ['specificError']
        assert not case['expected_valid']
        assert case['path'] == 'suite/tests/rule/bad.xbri'


def test_large_taxonomy_cache_tampering_is_repaired(tmp_path):
    from taxonomy_package import extract_verified
    archive = tmp_path/'tax.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('tax/META-INF/taxonomyPackage.xml','<taxonomyPackage/>')
        for i in range(101): z.writestr(f'tax/{i}.xsd',f'original-{i}')
    digest = sha256(archive.read_bytes()).hexdigest()
    root = extract_verified(archive,digest,tmp_path/'cache')
    (root/'100.xsd').write_text('tampered')
    restored = extract_verified(archive,digest,tmp_path/'cache')
    assert (restored/'100.xsd').read_text() == 'original-100'
