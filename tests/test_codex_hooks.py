"""Native host schemas and observed event shapes, not an invented hook protocol."""
import json
from pathlib import Path
from datetime import datetime, timezone

import pytest
from codeneuro.database import DomainError
from codeneuro.integrations.codex_hooks import (HookState, classify_command, handle_event, hook_config,
                                                terminal_evidence, patch_paths)


class Bridge:
    def __init__(self):
        self.calls = []
        self.decision = 'allow'
    def start_operation(self, **kwargs):
        self.calls.append(('start', kwargs))
        return {'id': 'operation-1'}
    def end_operation(self, operation_id, status):
        self.calls.append(('end', operation_id, status))
        return {}
    def context(self, path, request_id):
        self.calls.append(('context', path, request_id))
        return {'delivery_id': 'delivery-actual', 'rendered_markdown': 'Keep stable public exports.'}
    def preflight(self, **kwargs):
        self.calls.append(('preflight', kwargs))
        return {'decision': self.decision, 'id': 'preflight-real'}
    def record_test_run(self, **kwargs):
        self.calls.append(('test', kwargs))
        return {'id': 'test-real'}
    def cleanup(self, **kwargs):
        self.calls.append(('cleanup', kwargs))
        return {'closed': True}


def event(root, name='PreToolUse', command='cat src/unit.py', tool='Bash', data=None):
    return {'session_id': 'host-session', 'turn_id': 'turn-1', 'transcript_path': None, 'cwd': str(root),
        'hook_event_name': name, 'model': 'host-model', 'permission_mode': 'default', 'tool_name': tool,
        'tool_input': data if data is not None else {'command': command}, 'tool_use_id': 'call-1'}


@pytest.fixture
def env(tmp_path):
    (tmp_path/'src').mkdir()
    (tmp_path/'src/unit.py').write_text('value = 1\n')
    state = HookState(tmp_path)
    yield tmp_path, Bridge(), state
    state.close()


def test_observed_native_bash_read_injects_receipt_and_exact_path(env):
    root, bridge, state = env
    result = handle_event(event(root), workspace=root, bridge=bridge, state=state)
    assert result['hookSpecificOutput']['hookEventName'] == 'PreToolUse'
    assert 'delivery-actual' in result['hookSpecificOutput']['additionalContext']
    assert next(c for c in bridge.calls if c[0] == 'context')[1] == 'src/unit.py'
    assert 'permissionDecision' not in result['hookSpecificOutput']
    assert state.operation('host-session', 'call-1') == 'operation-1'
    handle_event(event(root, 'PostToolUse'), workspace=root, bridge=bridge, state=state)
    assert state.operation('host-session', 'call-1') is None
    assert bridge.calls[-1] == ('end', 'operation-1', 'completed')


def test_native_writes_are_checked_and_review_never_approves_permissions(env):
    root, bridge, state = env
    bridge.decision = 'review'
    result = handle_event(event(root, tool='Edit', data={'file_path': 'src/unit.py', 'old_string': 'value = 1\n',
                                                       'new_string': 'value = 2\n'}), workspace=root, bridge=bridge, state=state)
    assert result['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert 'preflight-real' in result['hookSpecificOutput']['permissionDecisionReason']
    assert '+value = 2' in next(c for c in bridge.calls if c[0] == 'preflight')[1]['diff']
    assert bridge.calls[-1] == ('end', 'operation-1', 'failed')


def test_shell_ambiguity_is_explicit_and_cannot_silently_bypass_scope(env):
    root, bridge, state = env
    result = handle_event(event(root, command="python -c 'import os; os.remove(\"file\")'"), workspace=root, bridge=bridge, state=state)
    assert result['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert not bridge.calls
    assert classify_command('cat "src/a b.py"')['paths'] == ['src/a b.py']
    assert classify_command('cat file; rm file')['kind'] == 'opaque'
    assert classify_command('Get-Content "C:\\repo\\a b.py"', windows=True)['paths'] == ['C:\\repo\\a b.py']


def test_workspace_paths_and_state_cannot_escape_symlinks(env, tmp_path_factory):
    root, bridge, state = env
    outside = tmp_path_factory.mktemp('outside')
    (root/'outside').symlink_to(outside)
    with pytest.raises(DomainError):
        handle_event(event(root, command='cat outside/private'), workspace=root, bridge=bridge, state=state)
    with pytest.raises(ValueError):
        handle_event({**event(root), 'cwd': str(outside)}, workspace=root, bridge=bridge, state=state)
    another = tmp_path_factory.mktemp('state-symlink')
    (another/'.codeneuro').symlink_to(outside)
    with pytest.raises(ValueError):
        HookState(another)


def test_post_hook_stdout_never_implies_test_success(env):
    root, bridge, state = env
    state.remember('host-session', 'call-1', ['src/unit.py'], 'test')
    result = handle_event({**event(root, 'PostToolUse', 'pytest'), 'tool_response': '100 passed\nexit_code=0'}, workspace=root, bridge=bridge, state=state)
    assert 'no test outcome was submitted' in result['hookSpecificOutput']['additionalContext']
    assert not any(c[0] == 'test' for c in bridge.calls)


def test_exact_terminal_transcript_event_supplies_actual_nonzero_evidence(env):
    root, bridge, state = env
    state.remember('host-session', 'call-1', ['src/unit.py'], 'test')
    transcript = root/'rollout.jsonl'
    transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'host-session'}})+'\n'+json.dumps({
        'type': 'event_msg', 'payload': {'type': 'item_completed', 'thread_id': 'host-session', 'turn_id': 'turn-1',
        'started_at_ms': 1700000000000, 'completed_at_ms': 1700000000123,
        'item': {'type': 'CommandExecution', 'id': 'call-1', 'status': 'failed', 'command': ['bash', '-lc', 'pytest'],
                 'exit_code': 1, 'stdout': '0 passed', 'stderr': 'assertion failed'}}})+'\n')
    ev = {**event(root, 'PostToolUse', 'pytest'), 'transcript_path': str(transcript), 'tool_response': 'misleading text'}
    result = handle_event(ev, workspace=root, bridge=bridge, state=state)
    actual = next(c[1] for c in bridge.calls if c[0] == 'test')
    assert actual['exit_code'] == 1 and actual['command'] == ['bash', '-lc', 'pytest']
    assert actual['stderr'] == 'assertion failed'
    assert 'test-real' in result['hookSpecificOutput']['additionalContext']
    assert terminal_evidence({**ev, 'tool_use_id': 'another-call'}, root) is None


def test_hook_config_is_scoped_has_no_trust_override_and_quotes_both_platforms():
    linux = hook_config('/a b/python', '/workspace a', windows=False)
    windows = hook_config('C:\\Python Path\\python.exe', 'C:\\My Project', windows=True)
    assert set(linux['hooks']) == {'PreToolUse', 'PostToolUse', 'SessionEnd'}
    assert "'/a b/python'" in linux['hooks']['PreToolUse'][0]['hooks'][0]['command']
    assert '"C:\\Python Path\\python.exe"' in windows['hooks']['PreToolUse'][0]['hooks'][0]['command']
    assert 'trusted_hash' not in json.dumps(linux) and 'bypass' not in json.dumps(linux)


def test_output_matches_extracted_codex_schema(env):
    import jsonschema
    root, bridge, state = env
    folder = Path(__file__).parent/'fixtures/codex-0.160'
    ev = event(root)
    jsonschema.validate(ev, json.loads((folder/'pre-tool-use.command.input.json').read_text()))
    response = handle_event(ev, workspace=root, bridge=bridge, state=state)
    jsonschema.validate(response, json.loads((folder/'pre-tool-use.command.output.json').read_text()))
    denied = handle_event(event(root, command='unknown operation'), workspace=root, bridge=bridge, state=state)
    jsonschema.validate(denied, json.loads((folder/'pre-tool-use.command.output.json').read_text()))
    assert patch_paths('*** Update File: src/a.py\n*** Move to: src/b.py') == ['src/a.py', 'src/b.py']
