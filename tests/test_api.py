"""Exercise the HTTP boundary: complete lifecycle and invalid requests."""
import pytest
from fastapi.testclient import TestClient
from codeneuro.api import create_app
from codeneuro.storage import Storage


@pytest.fixture
def client(tmp_path):
    storage=Storage(':memory:')
    with TestClient(create_app(storage=storage)) as client:yield client,tmp_path
    storage.close()


def test_real_lifecycle_from_prd_to_feedback_and_archive(client):
    c,root=client
    pid=c.post('/api/projects',json={'name':'test','root_paths':[str(root)]}).json()['id']
    task=c.post(f'/api/projects/{pid}/tasks',json={'title':'requirement'}).json()['id']
    response=c.post(f'/api/projects/{pid}/decompose',json={'task_id':task,'text':'# Update cache\n- src/cache.py\n- Set TTL to 60 seconds'})
    assert response.status_code==200
    rule=response.json()[0];assert rule['status']=='draft'
    query={'project_id':pid,'file_path':'src/cache.py','task_id':task}
    assert not c.get('/api/context',params=query).json()['short_term_rules']
    activated=c.patch(f"/api/rules/{rule['id']}/status",params={'status':'active','expected_version':rule['version']})
    assert activated.status_code==200
    session=c.post('/api/agent/sessions',json={'project_id':pid,'workspace_path':str(root),'task_id':task,'debug':True}).json()['id']
    delivered=c.post('/api/agent/context',json={'session_id':session,'file_path':'src/cache.py','request_id':'call-1'})
    assert delivered.status_code==200
    payload=delivered.json();assert 'Set TTL to 60 seconds' in payload['rendered_markdown']
    receipt=payload['delivery_id'];assert receipt
    repeated=c.post('/api/agent/context',json={'session_id':session,'file_path':'src/cache.py','request_id':'call-1'}).json()
    assert repeated['delivery_id']==receipt
    assert c.get('/api/stats').json()['total_hits']==1
    c.get('/api/context',params=query)
    assert c.get('/api/stats').json()['total_hits']==1
    feedback=c.post('/api/agent/feedback',json={'session_id':session,'delivery_id':receipt,'rule_id':rule['id'],'score':0})
    assert feedback.status_code==200
    reduced=c.post('/api/agent/context',json={'session_id':session,'file_path':'src/cache.py'}).json()
    assert reduced['reminders']
    assert 'Set TTL to 60 seconds' not in reduced['rendered_markdown']
    archived=c.patch(f'/api/tasks/{task}/status',params={'status':'archived'})
    assert archived.status_code==200
    assert not c.get('/api/context',params=query).json()['short_term_rules']
    assert c.get(f'/api/projects/{pid}/audit').json()
    assert c.get('/').status_code==200
    assert c.get('/static/app.js').status_code==200
    assert c.get('/api/health').json()['status']=='ok'


def test_http_validation_conflicts_and_export_boundary(client):
    c,root=client
    pid=c.post('/api/projects',json={'name':'test','root_paths':[str(root)]}).json()['id']
    req={'title':'contract','scope_patterns':['src/**'],'lifecycle':'long_term','content_points':['first']}
    rule=c.post(f'/api/projects/{pid}/rules',json=req).json()
    body={**req,'priority':'P0','expected_version':1,'content_points':['second']}
    assert c.put('/api/rules/'+rule['id'],json=body).status_code==200
    assert c.put('/api/rules/'+rule['id'],json=body).status_code==409
    assert c.post(f'/api/projects/{pid}/export',json={'format':'cursor','out_dir':str(root.parent)}).status_code==422
    assert c.post(f'/api/projects/{pid}/export',json={'format':'cursor','out_dir':str(root)}).status_code==200
    assert c.post(f'/api/projects/{pid}/rules',json={**req,'scope_patterns':['../escape']}).status_code==422
    assert c.post('/api/projects',json={'name':'csrf'},headers={'Origin':'http://attacker.invalid'}).status_code==403
    invalid=c.post(f'/api/projects/{pid}/findings',json={'id':'fake','project_id':pid,'target_path':'src/a.py','finding_text':'fake agent','source':'agent','session_id':'made-up'})
    assert invalid.status_code==422


def test_promotion_is_idempotent_and_deletion_preserves_history(client):
    c,root=client
    pid=c.post('/api/projects',json={'name':'test','root_paths':[str(root)]}).json()['id']
    finding={'id':'f','project_id':pid,'target_path':'src/a.py','finding_text':'observed'}
    assert c.post(f'/api/projects/{pid}/findings',json=finding).status_code==200
    r1=c.post('/api/findings/f/crystallize',json={'title':'reviewed'}).json()
    r2=c.post('/api/findings/f/crystallize',json={'title':'reviewed'}).json()
    assert r1['id']==r2['id']
    assert c.delete('/api/rules/'+r1['id'],params={'expected_version':r1['version']}).status_code==200
    assert len(c.get('/api/rules/'+r1['id']+'/versions').json())==2


def test_optional_token_protects_api(client,monkeypatch):
    c,_=client
    monkeypatch.setenv('CODENEURO_API_TOKEN','test-only-token')
    assert c.get('/api/stats').status_code==401
    assert c.get('/api/stats',headers={'Authorization':'Bearer test-only-token'}).status_code==200
