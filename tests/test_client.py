"""Client trust boundaries and real local I/O; HTTP transport is a declared test double."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import httpx
import pytest

from codeneuro.client import RemoteClient, discover_config, is_private_path, NativeBridge
from codeneuro.client_mcp import create_client_mcp
from codeneuro.database import DomainError, Conflict


class HubTransport:
    def __init__(self):
        self.calls = []
        self.decision = 'allow'
        self.before_preflight = None
        self.sessions = {}
        self.fail_status = False

    def __call__(self, request):
        assert request.url.host == 'hub.test'
        assert request.headers['authorization'] == 'Bearer test-client-secret'
        payload = json.loads(request.content)
        op, args = payload['op'], payload['args']
        self.calls.append((op, args))
        if op == 'start_session':
            result = {'id': 'session-' + str(len(self.sessions) + 1), 'project_id':'p', 'worktree_id':'w',
                      'task_id':args.get('task_id'), 'debug':args['debug'], 'binding_revision':0, 'state':'active'}
            self.sessions[result['id']] = result
        elif op == 'session_status':
            if self.fail_status:
                return httpx.Response(503, json={'detail':'Temporary observation failure'})
            result = self.sessions[args['session_id']]
        elif op == 'start_operation':
            result = {'id':args['request_id']}
        elif op == 'context':
            result = {'delivery_id':'receipt-'+str(len(self.calls)), 'session_id':args['session_id'],
                      'file_path':args['file_path'], 'rendered_markdown':'Actual test-double context contract.'}
        elif op == 'preflight':
            if self.before_preflight:
                self.before_preflight()
            result = {'decision':self.decision, 'stale':False, 'rules_checked':[]}
        elif op == 'test_run':
            result = {'id':'test-record', **args}
        elif op == 'cleanup':
            self.sessions[args['session_id']]['state'] = 'closed'
            result = {'state':'closed'}
        else:
            result = {'ok':True, **args}
        return httpx.Response(200, json={'result':result})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('CODENEURO_HOST_SESSION_ID', raising=False)
    monkeypatch.delenv('CODENEURO_AGENT_CLIENT', raising=False)
    monkeypatch.delenv('CODENEURO_HUB_URL', raising=False)
    (tmp_path/'src').mkdir()
    (tmp_path/'src/cache.py').write_text('value = 1\n')
    transport=HubTransport()
    config={'hub_url':'https://hub.test','project_id':'p','active_task':'t','token_env':'CODENEURO_TOKEN'}
    value=RemoteClient(config,tmp_path,trusted_hub_url='https://hub.test',token='test-client-secret',debug=True,
                       transport=httpx.MockTransport(transport))
    yield value,transport,tmp_path
    value.close()


def test_config_discovery_and_destination_cannot_be_authorized_by_repo(tmp_path, monkeypatch):
    monkeypatch.delenv('CODENEURO_HUB_URL',raising=False)
    (tmp_path/'nested').mkdir()
    config={'hub_url':'https://hub.test/','project_id':'p','active_task':None,'token_env':'CODENEURO_TOKEN'}
    (tmp_path/'.codeneuro.json').write_text(json.dumps(config))
    found=discover_config(tmp_path/'nested')
    assert found['hub_url']=='https://hub.test' and found['config_path']==str(tmp_path/'.codeneuro.json')
    with pytest.raises(DomainError,match='Explicitly pin'):
        RemoteClient(found,tmp_path,token='test-client-secret')
    with pytest.raises(DomainError,match='differs'):
        RemoteClient(found,tmp_path,trusted_hub_url='https://another.test',token='test-client-secret')
    config['token_env']='AWS_SECRET_ACCESS_KEY'
    (tmp_path/'.codeneuro.json').write_text(json.dumps(config))
    with pytest.raises(DomainError,match='dedicated'):
        discover_config(tmp_path)


def test_redirect_never_follows_or_forwards_token(client):
    c,_,root=client
    calls=[]
    def redirect(request):
        calls.append(str(request.url))
        return httpx.Response(307,headers={'location':'https://untrusted.test/api/client/rpc'})
    with RemoteClient(c.config,root,trusted_hub_url='https://hub.test',token='test-client-secret',
                      transport=httpx.MockTransport(redirect)) as other:
        with pytest.raises(DomainError,match='redirects'):
            other.start_session()
    assert calls==['https://hub.test/api/client/rpc']


@pytest.mark.parametrize('path',['../outside','src/../../outside','.env','.env.production','.aws/config','.ssh/id_rsa',
                                 '.codex/auth.json','secrets/config.toml','.codeneuro/native-sessions/x.json','private.pem'])
def test_file_tools_refuse_private_paths_before_any_rpc(client,path):
    c,transport,_=client
    with pytest.raises(DomainError):
        c.read_file(path)
    assert not transport.calls


def test_symlink_and_ancestor_escape_are_refused(client,tmp_path):
    c,transport,root=client
    (root/'link').symlink_to(root/'src',target_is_directory=True)
    (root/'src/link.py').symlink_to(root/'src/cache.py')
    for name in ('link/cache.py','src/link.py'):
        with pytest.raises(DomainError,match='Symlinks'):
            c.read_file(name)
    assert not transport.calls


def test_read_injects_context_and_edit_preserves_mode_with_real_diff(client):
    c,transport,root=client
    path=root/'src/cache.py';path.chmod(0o755)
    result=c.read_file('src/cache.py')
    assert result['content']=='value = 1\n' and result['delivery_id'].startswith('receipt-')
    assert [op for op,_ in transport.calls]==['start_session','start_operation','context','end_operation']
    edited=c.edit_file('src/cache.py','value = 2\n',result['sha256'],'Update cache value')
    assert edited['written'] and path.read_text()=='value = 2\n'
    assert path.stat().st_mode & 0o777==0o755
    preflight=next(args for op,args in transport.calls if op=='preflight')
    assert '-value = 1' in preflight['diff'] and '+value = 2' in preflight['diff']
    assert preflight['files']==['src/cache.py']
    assert not list((root/'src').glob('.codeneuro-edit-*'))


@pytest.mark.parametrize('decision',['block','review','unknown'])
def test_preflight_non_allow_cannot_write(client,decision):
    c,transport,root=client;transport.decision=decision
    before=c.read_file('src/cache.py')
    result=c.edit_file('src/cache.py','bad = 2\n',before['sha256'],'Requested edit')
    assert not result['written'] and (root/'src/cache.py').read_text()=='value = 1\n'


def test_changed_file_during_preflight_is_not_overwritten(client):
    c,transport,root=client
    original=c.read_file('src/cache.py')
    transport.before_preflight=lambda:(root/'src/cache.py').write_text('external = 3\n')
    with pytest.raises(Conflict,match='while the plan'):
        c.edit_file('src/cache.py','value = 2\n',original['sha256'],'Update value')
    assert (root/'src/cache.py').read_text()=='external = 3\n'
    assert transport.calls[-1][0]=='end_operation' and transport.calls[-1][1]['status']=='failed'


def test_missing_file_creation_requires_missing_cas_and_existing_parent(client):
    c,_,root=client
    result=c.edit_file('src/new.py','x = 2\n','missing','Add a small module')
    assert result['written'] and (root/'src/new.py').read_text()=='x = 2\n'
    with pytest.raises(DomainError,match='parent'):
        c.edit_file('absent/new.py','x = 2\n','missing','Add file')


def test_actual_test_result_and_token_environment_are_recorded(client,monkeypatch):
    c,transport,root=client
    monkeypatch.setenv('CODENEURO_TOKEN','test-client-secret')
    monkeypatch.setenv('SAMPLE_API_KEY','sensitive-sample-key')
    script=root/'check.py'
    script.write_text("import os,sys\nprint('token='+str(os.getenv('CODENEURO_TOKEN')))\nprint('key='+str(os.getenv('SAMPLE_API_KEY')))\nprint('real stdout')\nprint('real stderr',file=sys.stderr)\nsys.exit(3)\n")
    result=c.run_tests([sys.executable,'check.py'],['src/cache.py'])
    assert result['recorded'] and result['exit_code']==3 and result['stdout']=='token=None\nkey=None\nreal stdout\n'
    assert result['stderr']=='real stderr\n'
    assert result['started_at']<=result['finished_at']
    recorded=next(args for op,args in transport.calls if op=='test_run')
    assert recorded['exit_code']==3 and recorded['stdout']==result['stdout']
    artifact=Path(result['artifact'])
    assert artifact.exists() and artifact.stat().st_mode & 0o777==0o600
    assert 'test-client-secret' not in artifact.read_text()


def test_timeout_kills_real_process_tree(client):
    c,_,root=client
    (root/'child.py').write_text("from pathlib import Path\nimport time\ntime.sleep(2)\nPath('escaped-child.txt').write_text('alive')\n")
    (root/'hang.py').write_text("import subprocess,sys,time\nsubprocess.Popen([sys.executable,'child.py'])\ntime.sleep(30)\n")
    result=c.run_tests([sys.executable,'hang.py'],['src/cache.py'],timeout_seconds=1)
    assert result['timed_out'] and result['exit_code']!=0
    time.sleep(1.3)
    assert not (root/'escaped-child.txt').exists()


def test_test_shell_strings_and_external_file_args_are_refused(client):
    c,transport,root=client
    with pytest.raises(DomainError,match='shell'):
        c.run_tests(['bash','-c','true'],['src/cache.py'])
    with pytest.raises(DomainError,match='outside'):
        c.run_tests([sys.executable,str(root.parent/'outside.py')],['src/cache.py'])
    assert not transport.calls


def test_native_hook_and_sidecar_share_session_and_real_receipts(client):
    c,hub,root=client
    kwargs=dict(trusted_hub_url='https://hub.test',token='test-client-secret',debug=True,
                transport=httpx.MockTransport(hub),host_session_id='actual-host-session')
    with RemoteClient(c.config,root,**kwargs) as first:
        bridge=NativeBridge(first)
        delivery=bridge.context('src/cache.py','host-tool-call-1')
        sid=first.session_id
    with RemoteClient(c.config,root,**kwargs) as second:
        assert second.session_id==sid
        result=second.rate_rule(delivery['delivery_id'],'r',4,'Observed actual relevance in host context.')
        assert result['delivery_id']==delivery['delivery_id']
        assert sum(op=='start_session' for op,_ in hub.calls)==1
        second.cleanup()
        assert second.cleanup()=={'state':'closed'}
    state_text=''.join(p.read_text() for p in (root/'.codeneuro/native-sessions').glob('*.json'))
    assert 'test-client-secret' not in state_text and 'Actual test-double context' not in state_text
    with RemoteClient(c.config,root,**kwargs) as third:
        assert third.session_id!=sid


def test_temporary_session_status_failure_does_not_create_duplicate(client):
    c,hub,root=client
    kwargs=dict(trusted_hub_url='https://hub.test',token='test-client-secret',debug=True,
                transport=httpx.MockTransport(hub),host_session_id='host')
    with RemoteClient(c.config,root,**kwargs) as first:
        first.start_session()
    hub.fail_status=True
    with RemoteClient(c.config,root,**kwargs) as second:
        with pytest.raises(DomainError,match='Temporary'):
            second.start_session()
    assert sum(op=='start_session' for op,_ in hub.calls)==1


@pytest.mark.asyncio
async def test_mcp_tools_auto_inject_and_do_not_automatically_rate(client):
    c,hub,_=client
    server=create_client_mcp(c)
    names={t.name for t in await server.list_tools()}
    assert {'codeneuro_read_file','codeneuro_edit_file','codeneuro_run_tests','codeneuro_rate_rule','codeneuro_report_issue'}<=names
    result=await server.call_tool('codeneuro_read_file',{'file_path':'src/cache.py'})
    assert not result.is_error
    payload=json.loads(result.content[0].text)
    assert payload['delivery_id'] and payload['content']=='value = 1\n'
    assert not any(op=='feedback' for op,_ in hub.calls)
    plain=create_client_mcp(c,debug_mode=False)
    plain_names={t.name for t in await plain.list_tools()}
    assert 'codeneuro_rate_rule' not in plain_names and 'codeneuro_report_issue' not in plain_names
