from types import SimpleNamespace
from autotagger import recommend_tags
from docx_extract import SourceNode


def concept(qname, nl, en, period='instant'):
    return SimpleNamespace(qname=qname, label_nl=nl, label_en=en, period_type=period)


def test_labels_comparative_columns_and_ambiguity():
    table = SourceNode('t', 'table', 'body table 1', None, '',
                       rows=(('', '2026', '2025'), ('Vlottende activa', '1.234', '950')))
    concepts = [concept('t:Assets', 'Activa', 'Assets'),
                concept('t:CurrentAssets', 'Vlottende activa', 'Current assets')]
    recs = recommend_tags(table, concepts)
    assert len(recs) == 2
    assert [r['year_hint'] for r in recs] == [2026, 2025]
    assert all(r['qname'] == 't:CurrentAssets' for r in recs)
    assert recs[0]['value'] == '1234'
    assert recs[0]['source_text'] == '1.234'
    assert recs[0]['match_score'] == 1
    assert recs[0]['alternatives'] == ['t:Assets']


def test_unknown_period_is_not_guessed_and_no_match_is_not_tagged():
    table = SourceNode('t', 'table', 'body table 1', None, '',
                       rows=(('Revenue', '500'), ('Unrelated text', '100')))
    recs = recommend_tags(table, [concept('t:Revenue', 'Omzet', 'Revenue', 'duration')])
    assert len(recs) == 1
    assert recs[0]['year_hint'] is None
    assert recs[0]['period_type'] == 'duration'
