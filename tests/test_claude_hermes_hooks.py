import json
from pathlib import Path
import subprocess
import sys
import pytest

from codeneuro.integrations.codex_hooks import HookState
from codeneuro.integrations.claude_hooks import handle_claude, claude_config
from codeneuro.integrations.hermes_hooks import HermesHookState, handle_hermes
from codeneuro.integrations.hermes_plugin import register


class Bridge:
    def __init__(self):
        self.calls=[]
        self.decision='allow'
    def start_operation(self, **kwargs):
        self.calls.append(('start',kwargs));return {'id':'operation'}
    def end_operation(self, operation_id, status):
        self.calls.append(('end',status));return {}
    def context(self,path,request_id):
        self.calls.append(('context',path));return {'delivery_id':'receipt','rendered_markdown':'Preserve user-owned data.'}
    def preflight(self,**kwargs):
        self.calls.append(('preflight',kwargs));return {'id':'preflight','decision':self.decision}
    def record_test_run(self,**kwargs):
        self.calls.append(('test',kwargs));return {'id':'test-receipt'}
    def cleanup(self,request_id):
        self.calls.append(('cleanup',request_id));return {'closed':True}


@pytest.fixture
def env(tmp_path):
    (tmp_path/'src').mkdir();(tmp_path/'src/a.py').write_text('value=1\n')
    state=HermesHookState(tmp_path)
    yield tmp_path,Bridge(),state
    state.close()


def claude_event(root, name='PreToolUse', tool='Read', data=None):
    return {'hook_event_name':name,'tool_name':tool,'tool_input':data or {'file_path':str(root/'src/a.py')},
            'session_id':'claude-session','tool_use_id':'actual-call','cwd':str(root)}


def hermes_event(root, name='pre_tool_call', tool='read_file', data=None, result=None):
    return {'hook_event_name':name,'tool_name':tool,'tool_input':data or {'path':'src/a.py'},
            'session_id':'hermes-session','cwd':str(root),'extra':{'tool_call_id':'actual-call','result':result}}


def test_claude_read_hooks_inject_context_and_failure_closes_operation(env):
    root,bridge,state=env
    pre=handle_claude(claude_event(root),workspace=root,bridge=bridge,state=state)
    assert 'receipt' in pre['hookSpecificOutput']['additionalContext']
    assert state.operation('claude-session','actual-call')=='operation'
    handle_claude(claude_event(root,'PostToolUseFailure'),workspace=root,bridge=bridge,state=state)
    assert bridge.calls[-1]==('end','failed')
    assert state.operation('claude-session','actual-call') is None


def test_claude_edit_uses_preflight_and_missing_exit_code_never_creates_test_result(env):
    root,bridge,state=env
    bridge.decision='block'
    response=handle_claude(claude_event(root,tool='Edit',data={'file_path':'src/a.py','old_string':'value=1\n','new_string':'value=2\n'}),
                           workspace=root,bridge=bridge,state=state)
    assert response['hookSpecificOutput']['permissionDecision']=='deny'
    state.remember('claude-session','test-call',['src/a.py'],'test')
    response=handle_claude({**claude_event(root,'PostToolUse',tool='Bash',data={'command':'pytest'}),
                           'tool_use_id':'test-call','tool_response':{'stdout':'all passed','stderr':'','interrupted':False}},workspace=root,bridge=bridge,state=state)
    assert 'no test outcome was submitted' in response['hookSpecificOutput']['additionalContext']
    assert not any(c[0]=='test' for c in bridge.calls)
    assert set(claude_config(sys.executable,root)['hooks'])=={'PreToolUse','PostToolUse','PostToolUseFailure','SessionEnd'}


def test_hermes_real_result_is_preserved_and_context_is_consumed_at_transform(env):
    root,bridge,state=env
    assert handle_hermes(hermes_event(root),workspace=root,bridge=bridge,state=state)=={}
    original=json.dumps({'content':'1|value=1','path':'src/a.py'})
    handle_hermes(hermes_event(root,'post_tool_call',result=original),workspace=root,bridge=bridge,state=state)
    transformed=handle_hermes(hermes_event(root,'transform_tool_result',result=original),workspace=root,bridge=bridge,state=state)
    payload=json.loads(transformed['result'])
    assert payload['content']=='1|value=1'
    assert 'receipt' in payload['codeneuro_context']
    assert handle_hermes(hermes_event(root,'transform_tool_result',result=original),workspace=root,bridge=bridge,state=state)['result']==original
    assert bridge.calls[-1]==('end','completed')


def test_hermes_actual_nonzero_terminal_exit_is_recorded_and_null_is_not(env):
    root,bridge,state=env
    # Actual process outcome, carried by Hermes' documented result envelope.
    actual=subprocess.run([sys.executable,'-c','raise SystemExit(7)'],capture_output=True,text=True)
    state.remember('hermes-session','actual-call',['src/a.py'],'test')
    raw=json.dumps({'output':actual.stdout,'exit_code':actual.returncode,'error':None})
    handle_hermes(hermes_event(root,'post_tool_call',tool='terminal',data={'command':'pytest src/a.py'},result=raw),
                  workspace=root,bridge=bridge,state=state)
    evidence=next(c[1] for c in bridge.calls if c[0]=='test')
    assert evidence['exit_code']==7 and evidence['command']==['pytest','src/a.py']
    before=len(bridge.calls)
    handle_hermes(hermes_event(root,'post_tool_call',tool='terminal',data={'command':'pytest'},
                              result=json.dumps({'output':'looks successful','exit_code':None})),workspace=root,bridge=bridge,state=state)
    assert len(bridge.calls)==before


def test_hermes_workdir_is_resolved_in_workspace_and_background_scope_is_explicit(env):
    root,bridge,state=env
    response=handle_hermes(hermes_event(root,tool='terminal',data={'command':'cat a.py','workdir':str(root/'src')}),
                          workspace=root,bridge=bridge,state=state)
    assert response=={} and ('context','src/a.py') in bridge.calls
    blocked=handle_hermes(hermes_event(root,tool='terminal',data={'command':'pytest','background':True}),workspace=root,bridge=bridge,state=state)
    assert blocked['action']=='block'
    with pytest.raises(ValueError):
        bad=hermes_event(root);bad['extra']['tool_call_id']=None
        handle_hermes(bad,workspace=root,bridge=bridge,state=state)


def test_hermes_plugin_registers_actual_transform_hook_and_fails_closed(monkeypatch):
    handlers={}
    class Context:
        def register_hook(self,name,handler):handlers[name]=handler
    register(Context())
    assert set(handlers)=={'pre_tool_call','post_tool_call','transform_tool_result','on_session_finalize','on_session_reset'}
    monkeypatch.delenv('CODENEURO_PYTHON',raising=False)
    assert handlers['pre_tool_call'](tool_name='read_file',session_id='s',args={'path':'a'})['action']=='block'
    assert handlers['pre_tool_call'](tool_name='mcp_codeneuro_read',session_id='s') is None
