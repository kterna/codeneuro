"""Real registry/storage tests: no workstation path is touched on the Hub."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import threading

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from codeneuro.database import DomainError, Conflict
from codeneuro.models import Project, Task, Rule, Lifecycle, Priority
from codeneuro.remote import (RemoteRegistry, create_remote_router, ensure_schema,
                              normalize_remote_file, normalize_remote_workspace)
from codeneuro.storage import Storage


@pytest.fixture
def registry(tmp_path):
    store=Storage(str(tmp_path/'registry.db'))
    store.create_project(Project(id='p',name='project'))
    store.create_project(Project(id='other',name='other project'))
    store.create_task(Task(id='t',project_id='p',title='first task'))
    store.create_task(Task(id='t2',project_id='p',title='second task'))
    store.create_task(Task(id='foreign',project_id='other',title='other task'))
    value=RemoteRegistry(store)
    a=value.enroll('Windows workstation',['p'],admin_configured=True)
    b=value.enroll('Other workstation',['p'],admin_configured=True)
    outside=value.enroll('Other project client',['other'],admin_configured=True)
    yield value,store,a,b,outside
    store.close()


def started(registry,client,**extra):
    return registry.start_session(client['id'],project_id='p',workspace_path=r'C:\Work\Repo',
        machine_name='actual-test-workstation',platform='windows',task_id='t',debug=True,
        agent_client='Explicit registry test',**extra)


def test_enrollment_hash_only_sanitized_listing_and_revocation(registry):
    reg,store,a,_,_=registry
    row=dict(store.conn.execute('SELECT * FROM remote_clients WHERE id=?',(a['id'],)).fetchone())
    assert row['token_hash']==hashlib.sha256(a['token'].encode()).hexdigest()
    assert a['token'] not in json.dumps(row)
    listed=reg.list_clients()
    assert a['token'] not in json.dumps(listed) and 'token_hash' not in json.dumps(listed)
    auth=reg.authenticate(a['token'])
    assert auth['id']==a['id'] and auth['project_ids']==['p'] and 'token' not in auth
    for bad in (a['token'][:-1]+'!', 'cn1_unknown.bad', ''):
        with pytest.raises(DomainError) as exc:
            reg.authenticate(bad)
        assert exc.value.status==401
    reg.revoke(a['id']);reg.revoke(a['id'])
    with pytest.raises(DomainError) as exc:
        reg.authenticate(a['token'])
    assert exc.value.status==401
    with pytest.raises(DomainError,match='administrator'):
        reg.enroll('forbidden',['p'],admin_configured=False)


def test_additive_schema_does_not_change_core_version_or_existing_data(registry):
    reg,store,*_=registry
    before=store.conn.execute('PRAGMA user_version').fetchone()[0]
    ensure_schema(store);ensure_schema(store)
    assert store.conn.execute('PRAGMA user_version').fetchone()[0]==before
    assert store.get_project('p').name=='project'


@pytest.mark.parametrize('root,platform,path,expected',[
    (r'C:\Work\Repo','windows',r'c:\work\repo\src\cache.py','src/cache.py'),
    (r'C:\Work\Repo','windows',r'src\cache.py','src/cache.py'),
    (r'\\server\share\repo','windows',r'\\server\share\repo\a.py','a.py'),
    ('/home/dev/work','linux','/home/dev/work/src/cache.py','src/cache.py'),
    ('/home/dev/work','linux','src/cache.py','src/cache.py'),
])
def test_native_paths_are_lexical_and_anchored(root,platform,path,expected):
    assert normalize_remote_file(root,platform,path)==expected


@pytest.mark.parametrize('path',[r'C:\Other\x.py',r'C:relative.py',r'\root-relative.py',r'src\..\x.py',
                                r'src\auth.json:stream',r'src\NUL.txt',r'src\name.'])
def test_windows_outside_ambiguous_and_device_paths_fail(path):
    with pytest.raises(DomainError):
        normalize_remote_file(r'C:\Work\Repo','windows',path)


@pytest.mark.parametrize('root,platform',[('relative','linux'),('/work/../outside','linux'),
                                         (r'C:relative','windows'),(r'\\?\C:\root','windows')])
def test_invalid_workspace_paths_fail(root,platform):
    with pytest.raises(DomainError):
        normalize_remote_workspace(root,platform)


def test_remote_registration_never_resolves_or_checks_hub_filesystem(registry,monkeypatch):
    reg,store,a,b,_=registry
    def forbidden(*_args,**_kwargs):
        raise AssertionError('Remote workstation path was inspected on the Hub')
    monkeypatch.setattr(Path,'exists',forbidden)
    monkeypatch.setattr(Path,'resolve',forbidden)
    one=started(reg,a)
    repeat=reg.start_session(a['id'],project_id='p',workspace_path=r'c:\work\repo',
        machine_name='actual-test-workstation',platform='windows',task_id='t',debug=True)
    two=started(reg,b)
    assert one['worktree_id']==repeat['worktree_id']
    assert one['worktree_id']!=two['worktree_id']
    wt=store.conn.execute('SELECT * FROM worktree_instances WHERE id=?',(one['worktree_id'],)).fetchone()
    assert wt['source']=='remote' and wt['worktree_path']==r'C:\Work\Repo'
    metadata=store.conn.execute('SELECT * FROM remote_workspaces WHERE worktree_id=?',(one['worktree_id'],)).fetchone()
    assert metadata['metadata_trust']=='client_attested'


def test_project_task_and_session_ownership_are_distinct(registry):
    reg,_,a,b,outside=registry
    one=started(reg,a)
    with pytest.raises(DomainError):
        reg.session_status(b['id'],one['id'])
    with pytest.raises(DomainError):
        reg.rpc(b['id'],'context',{'session_id':one['id'],'file_path':'src/cache.py'})
    with pytest.raises(DomainError):
        reg.rpc(a['id'],'list_tasks',{'project_id':'other'})
    with pytest.raises(DomainError):
        reg.start_session(a['id'],project_id='p',workspace_path='/work/repo',machine_name='test',platform='linux',task_id='foreign')
    with pytest.raises(DomainError):
        reg.rpc(outside['id'],'graph',{'project_id':'p','worktree_id':one['worktree_id']})
    assert [p['id'] for p in reg.rpc(a['id'],'list_projects')]==['p']


def test_actual_receipts_and_versioned_feedback_are_held_by_owned_session(registry):
    reg,store,a,b,_=registry
    store.create_rule(Rule(id='r',project_id='p',task_id='t',title='scope',scope_patterns=['src/**'],content_points=['Keep caller input unchanged.']))
    one=started(reg,a)
    receipt=reg.rpc(a['id'],'context',{'session_id':one['id'],'file_path':r'C:\Work\Repo\src\cache.py','request_id':'real-rpc-1'})
    assert receipt['file_path']=='src/cache.py' and receipt['delivery_id']
    assert store.get_rule('r').hit_count==1
    assert reg.rpc(a['id'],'context',{'session_id':one['id'],'file_path':'src/cache.py','request_id':'real-rpc-1'})['delivery_id']==receipt['delivery_id']
    assert store.get_rule('r').hit_count==1
    result=reg.rpc(a['id'],'feedback',{'session_id':one['id'],'delivery_id':receipt['delivery_id'],'rule_id':'r','score':4,'reason':'Explicit registry feedback test.'})
    assert result['score']==4
    with pytest.raises(DomainError):
        reg.rpc(b['id'],'feedback',{'session_id':one['id'],'delivery_id':receipt['delivery_id'],'rule_id':'r','score':5})


def test_operation_boundary_idempotency_and_rebind_revision(registry):
    reg,store,a,_,_=registry
    session=started(reg,a)
    op=reg.start_operation(a['id'],session['id'],'edit',['src/cache.py'],'host-tool-1')
    assert reg.start_operation(a['id'],session['id'],'edit',['src/cache.py'],'host-tool-1')['id']==op['id']
    with pytest.raises(Conflict,match='active'):
        reg.bind_task(a['id'],session['id'],'t2',0)
    with pytest.raises(Conflict):
        reg.start_operation(a['id'],session['id'],'edit',['src/other.py'],'host-tool-1')
    finished=reg.end_operation(a['id'],session['id'],op['id'],'completed')
    assert finished['status']=='completed' and 'not a test result' in finished['outcome_scope']
    assert reg.end_operation(a['id'],session['id'],op['id'],'completed')['id']==op['id']
    assert reg.start_operation(a['id'],session['id'],'edit',['src/cache.py'],'host-tool-1')['status']=='completed'
    with pytest.raises(Conflict):
        reg.end_operation(a['id'],session['id'],op['id'],'failed')
    bound=reg.bind_task(a['id'],session['id'],'t2',0)
    assert bound['binding_revision']==1 and bound['task_id']=='t2'
    with pytest.raises(Conflict,match='revision'):
        reg.bind_task(a['id'],session['id'],'t',0)
    with pytest.raises(Conflict,match='binding'):
        reg.start_operation(a['id'],session['id'],'edit',['src/cache.py'],'host-tool-1')
    if store.conn.execute("SELECT name FROM sqlite_master WHERE name='governance_test_runs'").fetchone():
        assert store.conn.execute('SELECT count(*) FROM governance_test_runs').fetchone()[0]==0


def test_expired_lease_never_silently_counts_as_finished(registry):
    reg,store,a,_,_=registry
    session=started(reg,a)
    op=reg.start_operation(a['id'],session['id'],'test',['src/cache.py'],'test-operation')
    store.conn.execute('UPDATE remote_operations SET lease_until=? WHERE id=?',
                       ((datetime.utcnow()-timedelta(seconds=1)).isoformat(),op['id']))
    assert reg.session_status(a['id'],session['id'])['active_operation']['lease_expired']
    with pytest.raises(Conflict,match='unverified'):
        reg.bind_task(a['id'],session['id'],'t2',0)
    with pytest.raises(DomainError):
        reg.reconcile_operation(a['id'],session['id'],op['id'],'No actual check was made',False)
    result=reg.reconcile_operation(a['id'],session['id'],op['id'],'Client checked process handle and observed termination',True)
    assert result['status']=='reconciled'
    assert reg.bind_task(a['id'],session['id'],'t2',0)['task_id']=='t2'


def test_concurrent_clients_cannot_open_two_operations_for_same_session(registry,tmp_path):
    reg,store,a,_,_=registry
    session=started(reg,a)
    other_store=Storage(str(tmp_path/'registry.db'))
    other=RemoteRegistry(other_store)
    barrier=threading.Barrier(2)
    def open_operation(pair):
        registry,index=pair;barrier.wait()
        try:
            return registry.start_operation(a['id'],session['id'],'read',['src/cache.py'],f'parallel-{index}')['id']
        except Conflict:
            return 'conflict'
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(open_operation,[(reg,1),(other,2)]))
        assert results.count('conflict')==1
        assert store.conn.execute("SELECT count(*) FROM remote_operations WHERE status='active'").fetchone()[0]==1
    finally:
        other_store.close()


def test_rpc_does_not_accept_human_review_capabilities_or_cross_project_issue_rules(registry):
    reg,store,a,_,_=registry
    session=started(reg,a)
    for op in ('apply_proposal','apply_suggestion','set_policy','enroll','revoke','approve','__getattribute__'):
        with pytest.raises(DomainError):
            reg.rpc(a['id'],op,{'reviewed':True})
    with pytest.raises(DomainError,match='arguments'):
        reg.rpc(a['id'],'create_rule',{'session_id':session['id'],'title':'x','content_points':['x'],'scope_patterns':['**'],'reason':'x','reviewed':True})
    store.create_rule(Rule(id='foreign-rule',project_id='other',lifecycle=Lifecycle.LONG_TERM,title='foreign'))
    with pytest.raises(DomainError,match='outside'):
        reg.rpc(a['id'],'issue',{'session_id':session['id'],'issue_type':'other','title':'wrong rule','description':'test','file_path':'src/cache.py','related_rule_ids':['foreign-rule']})
    proposal=reg.rpc(a['id'],'propose_contract',{'session_id':session['id'],'target_component':'src/**','proposed_contract':'Keep boundaries explicit.','justification':'Observed API behavior.'})
    assert proposal['status']=='pending'
    assert not store.list_rules('p')


def test_router_requires_actual_client_bearer_not_body_review_flag(registry):
    reg,_,a,_,_=registry
    app=FastAPI()
    @app.exception_handler(DomainError)
    def domain_error(_request,error):
        return JSONResponse(status_code=error.status,content={'detail':str(error)})
    app.include_router(create_remote_router(reg))
    with TestClient(app) as client:
        assert client.post('/api/client/rpc',json={'op':'list_projects','args':{}}).status_code==401
        headers={'Authorization':'Bearer '+a['token']}
        response=client.post('/api/client/rpc',headers=headers,json={'op':'list_projects','args':{}})
        assert response.status_code==200 and response.json()['result'][0]['id']=='p'
        denied=client.post('/api/client/rpc',headers=headers,json={'op':'apply_proposal','args':{'reviewed':True}})
        assert denied.status_code==403
        assert client.post('/api/client/rpc',headers=headers,json={'op':'list_projects','args':{},'reviewed':True}).status_code==422


@pytest.mark.parametrize('kind',['read','write','test','search','inspect'])
def test_native_host_operation_kinds_are_supported(registry,kind):
    reg,_,a,_,_=registry
    session=started(reg,a)
    result=reg.start_operation(a['id'],session['id'],kind,['src/cache.py'],'native-'+kind)
    assert result['kind']==kind and result['status']=='active'
    reg.end_operation(a['id'],session['id'],result['id'],'completed')


def test_preflight_releases_transaction_and_rechecks_revocation(registry):
    reg,store,a,_,_=registry
    session=started(reg,a)
    class ProviderBoundary:
        def preflight(self,**args):
            assert not store.conn.in_transaction, 'Provider I/O must not hold SQLite transaction'
            assert args['files']==['src/cache.py']
            reg.revoke(a['id'])
            return {'decision':'allow'}
    reg.governance=ProviderBoundary()
    with pytest.raises(DomainError) as exc:
        reg.rpc(a['id'],'preflight',{'session_id':session['id'],'request_id':'revocation-test',
            'files':[r'C:\Work\Repo\src\cache.py'],'plan':'A real plan','diff':''})
    assert exc.value.status==401


@pytest.mark.parametrize('op,args',[
    ('context',{'session_id':{},'file_path':'a.py'}),
    ('list_tasks',{'project_id':['p']}),
    ('preflight',{'session_id':'s','request_id':'r','files':'a.py','plan':'test'}),
    ('start_session',{'project_id':'p','workspace_path':'/work','machine_name':'pc','platform':'linux','debug':'true'}),
])
def test_malformed_rpc_types_fail_as_domain_errors(registry,op,args):
    reg,_,a,_,_=registry
    with pytest.raises(DomainError) as exc:
        reg.rpc(a['id'],op,args)
    assert exc.value.status==422
