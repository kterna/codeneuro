"""Verify the workbench inspector against actual delivered session receipts."""
from fastapi.testclient import TestClient
from codeneuro.api import create_app
from codeneuro.models import Lifecycle, Priority, Project, Rule, Task, TaskStatus
from codeneuro.service import ContextService
from codeneuro.storage import Storage


def test_inspector_counts_actual_deliveries_and_preserves_preview_semantics(tmp_path):
    store=Storage(':memory:')
    store.create_project(Project(id='p',name='sample',root_paths=[str(tmp_path)]))
    store.create_project(Project(id='other',name='other',root_paths=[str(tmp_path)]))
    store.create_task(Task(id='t',project_id='p',title='current'))
    store.create_rule(Rule(id='global',project_id='p',title='long-lived',priority=Priority.P0,
                           lifecycle=Lifecycle.LONG_TERM,scope_patterns=['**'],content_points=['required']))
    store.create_rule(Rule(id='temporary',project_id='p',task_id='t',title='iteration',
                           scope_patterns=['src/**'],content_points=['task-specific']))
    service=ContextService(store)
    first=service.start_session('p',str(tmp_path),'t',agent_client='agent one')['id']
    second=service.start_session('p',str(tmp_path),'t',agent_client='agent two')['id']
    for sid in (first,first,second):service.resolve(session_id=sid,file_path='src/feature.py')
    with TestClient(create_app(storage=store)) as http:
        before=http.get('/api/stats').json()['total_hits']
        result=http.get('/api/projects/p/inspector',params={'path':'src/feature.py','task_id':'t','days':7})
        assert result.status_code==200,result.text
        data=result.json()
        assert {x['rule']['id'] for x in data['rules']}=={'global','temporary'}
        assert data['delivery_count']==3
        assert {x['agent_name']:x['deliveries'] for x in data['agent_stats']}=={'agent one':2,'agent two':1}
        assert len({x['delivery_id'] for x in data['deliveries']})==3
        assert http.get('/api/stats').json()['total_hits']==before
        cross=http.get('/api/projects/other/inspector',params={'path':'src/feature.py','task_id':'t'})
        assert cross.status_code==422
        store.update_task_status('t',TaskStatus.ARCHIVED)
        after=http.get('/api/projects/p/inspector',params={'path':'src/feature.py','task_id':'t'}).json()
        assert {x['rule']['id'] for x in after['rules']}=={'global'}
        assert after['delivery_count']==3  # Historical evidence remains visible.
    store.close()
