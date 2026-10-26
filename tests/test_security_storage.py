from contextvars import copy_context
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile
import hashlib
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app import auth
from app.store import WorkspaceStore, StorageUnavailable, StorageConflict, current_actor, read_versions
from taxonomy_package import extract_verified
from tests.test_regressions import snapshot, document, api


@pytest.fixture(autouse=True)
def isolated_actor():
    actor = current_actor.set('alice@example.test')
    versions = read_versions.set({})
    yield
    current_actor.reset(actor)
    read_versions.reset(versions)


def test_auth_never_accepts_plaintext_or_provider_marker():
    assert not auth.verify_password('supabase_auth', 'supabase_auth')
    assert not auth.verify_password('old-plaintext-password', 'old-plaintext-password')
    salt = bytes.fromhex('ab' * 16)
    digest = hashlib.pbkdf2_hmac('sha256', b'correct-password', salt, 100000).hex()
    encoded = salt.hex() + ':' + digest
    assert auth.verify_password('correct-password', encoded)
    assert not auth.verify_password(encoded, encoded)
    assert not auth.verify_password('wrong', encoded)


def test_unknown_or_removed_account_is_rejected(monkeypatch):
    monkeypatch.setattr(auth,'get_allowed_users',lambda:{})
    token = auth.create_access_token({'sub':'removed@example.test'})
    request = Request({'type':'http','headers':[(b'cookie',('access_token='+token).encode())]})
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(request)
    assert exc.value.status_code == 401


def test_two_releases_and_cache_tampering(tmp_path):
    roots=[]
    for name in ('old','new','old'):
        package=tmp_path/(name+'.zip')
        if not package.exists():
            with ZipFile(package,'w') as z:
                z.writestr('META-INF/taxonomyPackage.xml',name)
        root=extract_verified(package,sha256(package.read_bytes()).hexdigest(),tmp_path/'cache')
        assert (root/'META-INF/taxonomyPackage.xml').read_text()==name
        roots.append(root)
    assert roots[0] == roots[2] and roots[0] != roots[1]
    (roots[0]/'META-INF/taxonomyPackage.xml').write_text('corrupted')
    p=tmp_path/'old.zip'
    repaired=extract_verified(p,sha256(p.read_bytes()).hexdigest(),tmp_path/'cache')
    assert (repaired/'META-INF/taxonomyPackage.xml').read_text()=='old'


def test_save_survives_new_store_and_is_private(tmp_path):
    store=WorkspaceStore(local_dir=tmp_path)
    snap=snapshot();store.add_document(document());store.add(snap)
    assert store.save_to_disk(snap.kvk_number,snap.filing_id)
    restarted=WorkspaceStore(local_dir=tmp_path)
    assert restarted.load_from_disk(snap.kvk_number).filing_id==snap.filing_id
    assert restarted.get_document(snap.document_sha256).sha256==snap.document_sha256
    current_actor.set('bob@example.test')
    assert restarted.list_filings()==[]
    with pytest.raises(KeyError): restarted.get(snap.filing_id)
    with pytest.raises(KeyError): restarted.get_document(snap.document_sha256)
    with pytest.raises(FileNotFoundError): restarted.load_from_disk(snap.kvk_number)


def test_unconfigured_storage_cannot_report_success(monkeypatch):
    monkeypatch.delenv('KVK_LOCAL_DATA_DIR',raising=False)
    from app import supabase_client
    def unavailable(): raise RuntimeError('offline')
    monkeypatch.setattr(supabase_client,'get_supabase',unavailable)
    store=WorkspaceStore()
    with pytest.raises(StorageUnavailable):store.add(snapshot())
    with pytest.raises(StorageUnavailable):store.save_to_disk('12345678','test-filing')


def test_concurrent_updates_do_not_overwrite(tmp_path):
    store=WorkspaceStore(local_dir=tmp_path);store.add(snapshot())
    other=copy_context()
    stale=other.run(store.get,'test-filing')
    fresh=store.get('test-filing');fresh.entity_name='New name';store.update(fresh)
    stale.entity_name='Stale name'
    with pytest.raises(StorageConflict):other.run(store.update,stale)
    assert store.get('test-filing').entity_name=='New name'


def test_api_isolates_filings_and_admin_actions(api,monkeypatch):
    client,main=api
    main.store.add(snapshot());main.store.add_document(document())
    monkeypatch.setattr(main,'get_current_user',lambda request:'other@example.test')
    monkeypatch.setattr(main,'get_user_role',lambda actor:'preparer')
    assert client.get('/api/snapshot/test-filing').status_code==404
    assert client.get('/api/workspace/list').json()=={'filings':[]}
    assert client.post('/api/admin/taxonomy/test/deactivate').status_code==403
    assert client.post('/api/snapshot/test-filing/reopen').status_code==404


def test_package_output_size_limit(monkeypatch):
    import package
    from tests.test_regressions import registry
    monkeypatch.setattr(package,'MAX_REPORT_PACKAGE_BYTES',10)
    with pytest.raises(ValueError,match='limit'):
        package.create_report_package(snapshot(),registry().get('test'),b'<html/>')


def test_api_export_state_is_durable(api,monkeypatch):
    from service import FilingService
    client,main=api
    snap=snapshot();snap.freeze();main.store.add(snap);main.store.add_document(document())
    monkeypatch.setattr(main,'filing_service',FilingService(main.taxonomy_registry,lambda *_: []))
    assert client.post('/api/snapshot/test-filing/validate-and-package').status_code==200
    assert main.store.get('test-filing').state.value=='validated'
    events=client.get('/api/snapshot/test-filing/audit').json()['events']
    assert events[-1]['actor']=='reviewer@example.test'
    assert events[-1]['state']=='validated'


def test_cloud_owner_filters_and_failure_are_enforced(monkeypatch):
    from types import SimpleNamespace
    from copy import deepcopy
    from app import supabase_client
    tables={}
    class Query:
        def __init__(self,table): self.table=table;self.filters={};self.operation='select';self.payload=None
        def select(self,*args): return self
        def eq(self,k,v): self.filters[k]=v;return self
        def insert(self,row): self.operation='insert';self.payload=deepcopy(row);return self
        def update(self,row): self.operation='update';self.payload=deepcopy(row);return self
        def execute(self):
            rows=tables.setdefault(self.table,[])
            if self.operation=='insert': rows.append(self.payload);return SimpleNamespace(data=[self.payload])
            found=[r for r in rows if all(r.get(k)==v for k,v in self.filters.items())]
            if self.operation=='update':
                for row in found: row.update(self.payload)
            return SimpleNamespace(data=deepcopy(found))
    fake=SimpleNamespace(table=lambda table:Query(table))
    monkeypatch.delenv('KVK_LOCAL_DATA_DIR',raising=False)
    monkeypatch.setattr(supabase_client,'get_supabase',lambda:fake)
    store=WorkspaceStore();store.add(snapshot());store.add_document(document())
    loaded=store.get('test-filing');loaded.entity_name='Cloud edit';store.update(loaded)
    assert tables['filings'][0]['created_by']=='alice@example.test'
    assert tables['filings'][0]['version']==2
    assert WorkspaceStore().get('test-filing').entity_name=='Cloud edit'
    current_actor.set('bob@example.test')
    with pytest.raises(KeyError):store.get('test-filing')
    with pytest.raises(KeyError):store.get_document(document().sha256)
    current_actor.set('alice@example.test')
    def offline(): raise RuntimeError('database offline')
    monkeypatch.setattr(supabase_client,'get_supabase',offline)
    with pytest.raises(StorageUnavailable):store.get('test-filing')
    with pytest.raises(StorageUnavailable):store.save_to_disk('12345678','test-filing')


def test_parallel_taxonomy_loads_keep_release_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    packages=[]
    for name in ('a','b'):
        path=tmp_path/(name+'.zip')
        with ZipFile(path,'w') as z:z.writestr('META-INF/taxonomyPackage.xml',name)
        packages.append((path,sha256(path.read_bytes()).hexdigest(),name))
    def load(item):
        path,digest,name=item
        root=extract_verified(path,digest,tmp_path/'cache')
        return (root/'META-INF/taxonomyPackage.xml').read_text()==name
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(load,packages*3))
