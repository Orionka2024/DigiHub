from pathlib import Path
import pytest
from taxonomy_parser import TaxonomyParser


def schema(path, prefix, name, imports=''):
    path.write_text(f'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
      xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:{prefix}="urn:{prefix}"
      targetNamespace="urn:{prefix}">
      <xs:element id="{prefix}_{name}" name="{name}" substitutionGroup="xbrli:item"
        type="xbrli:stringItemType" xbrli:periodType="duration"/>{imports}</xs:schema>''')


def test_independent_entry_points_and_namespaces(tmp_path):
    schema(tmp_path/'a.xsd', 'a', 'Assets')
    schema(tmp_path/'b.xsd', 'b', 'Assets')
    parser = TaxonomyParser(tmp_path)
    a, _ = parser.parse_entry_point('a.xsd', 'a')
    b, _ = parser.parse_entry_point('b.xsd', 'b')
    assert set(a) == {'a:Assets'}
    assert set(b) == {'b:Assets'}
    assert a['a:Assets'].entry_points == ['a']
    assert b['b:Assets'].entry_points == ['b']


def test_shared_import_is_in_both_entry_points(tmp_path):
    schema(tmp_path/'shared.xsd', 'shared', 'Assets')
    for ep in ('a', 'b'):
        schema(tmp_path/f'{ep}.xsd', ep, 'Own', '<xs:import namespace="urn:shared" schemaLocation="shared.xsd"/>')
    parser = TaxonomyParser(tmp_path)
    for ep in ('a', 'b'):
        concepts, _ = parser.parse_entry_point(f'{ep}.xsd', ep)
        assert concepts['shared:Assets'].entry_points == [ep]


def test_missing_schema_is_an_error(tmp_path):
    with pytest.raises(ValueError, match='Unresolved'):
        TaxonomyParser(tmp_path).parse_entry_point('absent.xsd', 'missing')


def test_missing_import_is_an_error(tmp_path):
    schema(tmp_path/'a.xsd', 'a', 'Own', '<xs:import schemaLocation="missing.xsd"/>')
    with pytest.raises(ValueError, match='Unresolved'):
        TaxonomyParser(tmp_path).parse_entry_point('a.xsd', 'a')
