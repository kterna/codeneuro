"""Real local exports driven by a declared authenticated-RPC fixture."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time

import pytest
from codeneuro.database import Conflict, DomainError
from codeneuro.models import Lifecycle, Priority, Rule, RuleStatus
from codeneuro.sync import StaticSync, _lease


class ScopedHub:
    def __init__(self, root):
        self.workspace = root
        self.project_id = 'project'
        self.rule = Rule(id='contract', project_id='project', title='Contract', lifecycle=Lifecycle.LONG_TERM,
                         content_points=['Do not mutate callers.'], scope_patterns=['src/**'], priority=Priority.P0)
        self.short = Rule(id='task-a', project_id='project', task_id='a', title='Task A',
                          content_points=['Temporary behavior A'], scope_patterns=['src/**'])
        self.payload = {'project_id': 'project', 'task_id': 'a', 'binding_revision': 0,
                        'rules': [self.rule.model_dump(mode='json'), self.short.model_dump(mode='json')]}
        self.requests = []
        self.fail = False
        self.on_rpc = None
    def start_session(self):
        return {'id': 'actual-owned-session'}
    def rpc(self, op, args):
        assert op == 'export_rules' and args == {'session_id': 'actual-owned-session'}
        self.requests.append((op, args))
        if self.fail:
            raise DomainError('network temporarily unavailable', 'hub_unavailable', 503)
        if self.on_rpc:
            self.on_rpc(len(self.requests))
        return deepcopy(self.payload)


@pytest.fixture
def client(tmp_path):
    (tmp_path/'CLAUDE.md').write_text('# Human instructions\nKeep this paragraph.\n', encoding='utf-8')
    directory = tmp_path/'.cursor/rules'; directory.mkdir(parents=True)
    (directory/'human.mdc').write_text('human rules\n', encoding='utf-8')
    return ScopedHub(tmp_path)


def generated(root):
    return '\n'.join(path.read_text(encoding='utf-8') for path in (root/'.cursor/rules').glob('codeneuro-*.mdc'))


def test_initial_export_scope_versions_and_human_content_are_preserved(client):
    sync = StaticSync(client)
    result = sync.sync_once()
    assert result['state'] == 'current' and result['rule_count'] == 2
    assert result['task_id'] == 'a' and result['binding_revision'] == 0
    assert 'Temporary behavior A' in generated(client.workspace)
    assert (client.workspace/'.cursor/rules/human.mdc').read_text() == 'human rules\n'
    assert '# Human instructions\nKeep this paragraph.' in (client.workspace/'CLAUDE.md').read_text()
    again = sync.sync_once()
    assert not again['changed']
    status = json.loads((client.workspace/'.codeneuro/sync-status.json').read_text())
    assert status['transport'] == 'poll' and status['managed_snapshots_valid']
    assert 'Temporary behavior A' not in json.dumps(status)


def test_rule_update_task_switch_and_archive_remove_previous_snapshots(client):
    sync = StaticSync(client)
    sync.sync_once()
    new = client.short.model_copy(update={'id': 'task-b', 'task_id': 'b', 'title': 'Task B', 'content_points': ['Behavior B']})
    client.payload.update(task_id='b', binding_revision=1, rules=[client.rule.model_dump(mode='json'), new.model_dump(mode='json')])
    result = sync.sync_once()
    assert result['task_id'] == 'b' and result['binding_revision'] == 1
    assert 'Temporary behavior A' not in generated(client.workspace)
    assert 'Behavior B' in generated(client.workspace)
    assert 'Temporary behavior A' not in (client.workspace/'CLAUDE.md').read_text()
    # An archived/paused task still has a pinned task id but export_rules excludes
    # its temporary rules. The watcher must not resurrect prior snapshots.
    client.payload['rules'] = [client.rule.model_dump(mode='json')]
    sync.sync_once()
    assert 'Behavior B' not in generated(client.workspace)
    assert 'Do not mutate callers.' in generated(client.workspace)


def test_outage_invalidates_only_managed_rules_and_retry_restores_current(client):
    sync = StaticSync(client, poll_interval=.05, max_backoff=.2)
    sync.sync_once()
    client.fail = True
    first = sync.sync_once(); second = sync.sync_once()
    assert first['state'] == second['state'] == 'stale'
    assert not first['managed_snapshots_valid'] and first['invalidation_error'] is None
    assert first['next_retry_seconds'] == .05 and second['next_retry_seconds'] == .1
    assert first['last_success_at'] and not generated(client.workspace)
    assert 'Temporary behavior A' not in (client.workspace/'CLAUDE.md').read_text()
    assert (client.workspace/'.cursor/rules/human.mdc').read_text() == 'human rules\n'
    client.payload['rules'] = [client.rule.model_dump(mode='json')]
    client.fail = False
    restored = sync.sync_once()
    assert restored['state'] == 'current' and restored['rule_count'] == 1
    assert 'Temporary behavior A' not in generated(client.workspace)


def test_mixed_project_or_wrong_task_snapshot_fails_without_leakage(client):
    sync = StaticSync(client)
    sync.sync_once()
    client.payload['rules'][1]['task_id'] = 'other'
    result = sync.sync_once()
    assert result['state'] == 'stale' and not generated(client.workspace)
    client.payload['rules'][1]['task_id'] = 'a'
    client.payload['rules'][0]['project_id'] = 'outside'
    result = sync.sync_once()
    assert result['state'] == 'stale' and not generated(client.workspace)


def test_binding_change_during_publish_is_reconciled_before_current_status(client):
    sync = StaticSync(client)
    def switch(count):
        if count == 2:
            client.payload.update(task_id='b', binding_revision=1, rules=[client.rule.model_dump(mode='json')])
    client.on_rpc = switch
    result = sync.sync_once()
    assert result['state'] == 'current' and result['task_id'] == 'b'
    assert len(client.requests) == 4
    assert 'Temporary behavior A' not in generated(client.workspace)


def test_manual_generated_edits_are_preserved_and_conflict_is_visible(client):
    sync = StaticSync(client)
    sync.sync_once()
    path = next((client.workspace/'.cursor/rules').glob('codeneuro-*.mdc'))
    path.write_text('Manual edit requiring reconciliation\n')
    client.payload['rules'] = []
    result = sync.sync_once()
    assert result['state'] == 'stale' and result['invalidation_error'] == 'Conflict'
    assert not result['managed_snapshots_valid']
    assert path.read_text() == 'Manual edit requiring reconciliation\n'


def test_unowned_name_collision_and_bad_manifest_never_overwrite_human_files(client):
    name = 'codeneuro-contract-' + hashlib.sha256(b'contract').hexdigest()[:24] + '.mdc'
    path = client.workspace/'.cursor/rules'/name
    path.write_text('human file with coincidental name')
    sync = StaticSync(client)
    result = sync.sync_once()
    assert result['state'] == 'stale' and path.read_text() == 'human file with coincidental name'
    (client.workspace/'.cursor/rules/.codeneuro-manifest.json').write_text(json.dumps({'files': ['../../human.mdc']}))
    result = sync.sync_once()
    assert result['state'] == 'stale' and result['invalidation_error'] == 'DomainError'
    assert (client.workspace/'.cursor/rules/human.mdc').exists()


def test_missing_generated_snapshot_is_restored_and_human_prose_can_change(client):
    sync = StaticSync(client)
    sync.sync_once()
    path = next((client.workspace/'.cursor/rules').glob('codeneuro-*.mdc'))
    path.unlink()
    claude = client.workspace/'CLAUDE.md'
    claude.write_text('Human addition\n' + claude.read_text())
    result = sync.sync_once()
    assert result['state'] == 'current' and result['changed'] and path.exists()
    assert claude.read_text().startswith('Human addition\n')


def test_watch_stops_promptly_and_invalidates_snapshots(client):
    ready, stop = threading.Event(), threading.Event()
    sync = StaticSync(client, poll_interval=.05, max_backoff=.2,
                      status_callback=lambda value: ready.set() if value['state'] == 'current' else None)
    result = []
    thread = threading.Thread(target=lambda: result.append(sync.watch(stop)))
    thread.start()
    assert ready.wait(3)
    stop.set();thread.join(2)
    assert not thread.is_alive() and result[0]['state'] == 'stopped'
    assert not generated(client.workspace)
    assert 'Keep this paragraph.' in (client.workspace/'CLAUDE.md').read_text()


def test_only_one_watcher_owns_workspace_and_symlinks_are_rejected(client,tmp_path):
    sync = StaticSync(client)
    with _lease(sync.state_dir/'sync.lock'):
        with pytest.raises(Conflict):
            sync.sync_once()
    outside = tmp_path/'outside';outside.mkdir()
    try:
        (client.workspace/'CLAUDE.md').unlink();(client.workspace/'CLAUDE.md').symlink_to(outside/'instructions.md')
    except OSError:
        pytest.skip('Symlink creation unavailable on this test account')
    assert sync.sync_once()['invalidation_error'] == 'DomainError'
    assert not (outside/'instructions.md').exists()


def test_sync_against_real_authenticated_remote_hub(tmp_path, monkeypatch):
    remote_client = pytest.importorskip('codeneuro.client', reason='Integrated remote client is supplied by the full-product branch')
    import httpx
    import secrets
    import socket
    import uvicorn
    from codeneuro.api import create_app
    from codeneuro.storage import Storage
    from codeneuro.models import Project, Task
    admin = secrets.token_urlsafe(32)
    monkeypatch.setenv('CODENEURO_API_TOKEN', admin)
    monkeypatch.delenv('CODENEURO_HOST_SESSION_ID', raising=False)
    monkeypatch.delenv('CODENEURO_AGENT_CLIENT', raising=False)
    workspace = tmp_path/'workspace'; workspace.mkdir()
    store = Storage(str(tmp_path/'hub.db'))
    store.create_project(Project(id='p',name='Temporary authenticated sync trial',root_paths=[str(workspace)]))
    store.create_task(Task(id='a',project_id='p',title='Initial task'))
    store.create_task(Task(id='b',project_id='p',title='Next task'))
    store.create_rule(Rule(id='short-a',project_id='p',task_id='a',title='A only',
                           scope_patterns=['src/**'],content_points=['Only A scope']))
    store.create_rule(Rule(id='short-b',project_id='p',task_id='b',title='B only',
                           scope_patterns=['src/**'],content_points=['Only B scope']))
    app = create_app(store)
    listener = socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen(16)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='on'))
    thread = threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    hub = f'http://127.0.0.1:{port}'
    client = None
    try:
        with httpx.Client(base_url=hub,headers={'Authorization':'Bearer '+admin},trust_env=False,timeout=3) as human:
            deadline = time.monotonic()+5
            while not server.started:
                if time.monotonic()>deadline:raise AssertionError('Temporary Hub did not become ready')
                time.sleep(.02)
            enrolled = human.post('/api/clients',json={'name':'sync HTTP acceptance','project_ids':['p']})
            assert enrolled.status_code==200,enrolled.text
            token=enrolled.json()['token']
            client=remote_client.RemoteClient({'hub_url':hub,'project_id':'p','active_task':'a','token_env':'CODENEURO_TOKEN'},
                                              workspace,trusted_hub_url=hub,token=token,agent_client='Sync integration fixture')
            sync=StaticSync(client,formats='cursor')
            assert sync.sync_once()['state']=='current'
            assert 'Only A scope' in generated(workspace) and 'Only B scope' not in generated(workspace)
            sid=client.session_id
            client.rpc('bind_task',{'session_id':sid,'task_id':'b','expected_revision':0})
            assert sync.sync_once()['task_id']=='b'
            assert 'Only B scope' in generated(workspace) and 'Only A scope' not in generated(workspace)
            archived=human.patch('/api/tasks/b/status',params={'status':'archived'})
            assert archived.status_code==200,archived.text
            assert sync.sync_once()['rule_count']==0 and not generated(workspace)
            assert token not in (workspace/'.codeneuro/sync-status.json').read_text()
    finally:
        if client:client.close()
        server.should_exit=True;thread.join(5);listener.close();store.close()
