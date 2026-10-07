"""Hermes native plugin worker using real pre/post/transform tool hooks."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from .codex_hooks import HookState, find_config, handle_event, _key, classify_command


class HermesHookState(HookState):
    def __init__(self, root):
        super().__init__(root)
        self.conn.execute('CREATE TABLE IF NOT EXISTS hermes_context(id TEXT PRIMARY KEY,content TEXT NOT NULL)')

    def add_context(self, sid, call, text):
        if not text:
            return
        with self.conn:
            old = self.conn.execute('SELECT content FROM hermes_context WHERE id=?', (_key(sid, call),)).fetchone()
            value = (old[0] + '\n\n' if old else '') + text
            self.conn.execute('INSERT OR REPLACE INTO hermes_context VALUES(?,?)', (_key(sid, call), value))

    def take_context(self, sid, call):
        with self.conn:
            row = self.conn.execute('SELECT content FROM hermes_context WHERE id=?', (_key(sid, call),)).fetchone()
            self.conn.execute('DELETE FROM hermes_context WHERE id=?', (_key(sid, call),))
        return row[0] if row else ''


def translate(event):
    extra = event.get('extra') or {}
    tool = event.get('tool_name', '')
    hook = event.get('hook_event_name')
    translated = {'session_id': event.get('session_id') or extra.get('session_id'), 'cwd': event['cwd'],
        'hook_event_name': {'pre_tool_call': 'PreToolUse', 'post_tool_call': 'PostToolUse', 'on_session_end': 'SessionEnd',
                            'on_session_finalize': 'SessionEnd'}.get(hook, hook),
        'tool_name': 'Bash' if tool == 'terminal' else tool,
        'tool_input': event.get('tool_input') or {},
        'tool_use_id': extra.get('tool_call_id') or event.get('tool_call_id'),
        'transcript_path': None,
        'tool_failed': extra.get('status') in ('error', 'blocked', 'cancelled')}
    if hook not in ('on_session_end', 'on_session_finalize') and not translated['tool_use_id']:
        raise ValueError('Hermes must provide its actual tool_call_id')
    # A terminal may request a subdirectory independently of the host process cwd.
    requested_cwd = translated['tool_input'].get('workdir') or translated['tool_input'].get('cwd')
    if requested_cwd:
        root = Path(event['cwd'])
        translated['cwd'] = str((root / requested_cwd).resolve())
    return translated


def handle_hermes(event, *, workspace, bridge, state: HermesHookState):
    hook = event.get('hook_event_name')
    translated = translate(event)
    sid, call = translated['session_id'], translated.get('tool_use_id')
    if not sid:
        raise ValueError('Hermes host session_id is required')
    if hook == 'transform_tool_result':
        original = (event.get('extra') or {}).get('result', '')
        context = state.take_context(sid, call)
        if not context:
            return {'result': original}
        try:
            result = json.loads(original) if isinstance(original, str) else original
        except (ValueError, TypeError):
            result = None
        if isinstance(result, dict):
            result = {**result, 'codeneuro_context': context}
            return {'result': json.dumps(result, ensure_ascii=False)}
        return {'result': str(original) + '\n\n<codeneuro-context>\n' + context + '\n</codeneuro-context>'}
    if hook == 'pre_tool_call':
        args = event.get('tool_input') or {}
        if event.get('tool_name') == 'terminal' and (args.get('background') or args.get('pty') or args.get('timeout', 180) > 180):
            return {'action': 'block', 'message': 'Use the CodeNeuro command tool for background or long terminal operations so the Hub can retain their live operation handle.'}
        response = handle_event(translated, workspace=workspace, bridge=bridge, state=state)
        specific = response.get('hookSpecificOutput', {})
        if specific.get('permissionDecision') == 'deny':
            return {'action': 'block', 'message': specific['permissionDecisionReason']}
        state.add_context(sid, call, specific.get('additionalContext', ''))
        return {}
    if hook == 'post_tool_call':
        extra = event.get('extra') or {}
        previous = state.event(sid, call)
        try:
            if previous and previous['kind'] == 'test':
                raw = extra.get('result')
                try:
                    result = json.loads(raw) if isinstance(raw, str) else raw
                except (ValueError, TypeError):
                    result = None
                code = result.get('exit_code') if isinstance(result, dict) else None
                if isinstance(code, int) and not isinstance(code, bool) and previous['paths'] and not result.get('error'):
                    command = classify_command((event.get('tool_input') or {}).get('command', ''), windows=os.name == 'nt')['argv']
                    recorded = bridge.record_test_run(request_id='hermes-test:' + call, command=command, exit_code=code,
                        stdout=result.get('output', ''), stderr='', started_at=previous['started_at'],
                        finished_at=datetime.now(timezone.utc).isoformat(), paths=previous['paths'])
                    state.add_context(sid, call, 'CodeNeuro recorded the actual Hermes terminal exit_code. Receipt: ' + str(recorded.get('id')))
                else:
                    state.add_context(sid, call, 'CodeNeuro did not receive a terminal exit_code and scoped paths; no test outcome was submitted.')
            return {}
        finally:
            operation_id = state.operation(sid, call)
            if operation_id:
                bridge.end_operation(operation_id, status='failed' if translated['tool_failed'] else 'completed')
                state.clear_operation(sid, call)
    if hook in ('on_session_end', 'on_session_finalize'):
        response = handle_event(translated, workspace=workspace, bridge=bridge, state=state)
        with state.conn:
            state.conn.execute('DELETE FROM hermes_context WHERE id IN (SELECT id FROM events WHERE host_session=?)', (sid,))
        return response
    return {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args(argv)
    state, event = None, {}
    try:
        raw = sys.stdin.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Hook input too large')
        event = json.loads(raw)
        root = args.workspace.resolve()
        from codeneuro.client import create_native_bridge
        bridge = create_native_bridge(config_path=find_config(root), workspace=root,
                                      host_session_id=event['session_id'], agent_client='Hermes')
        state = HermesHookState(root)
        print(json.dumps(handle_hermes(event, workspace=root, bridge=bridge, state=state), ensure_ascii=False))
        return 0
    except Exception as exc:
        message = 'CodeNeuro Hermes bridge failed (' + type(exc).__name__ + '). Check the workspace and trusted Hub.'
        if event.get('hook_event_name') == 'pre_tool_call':
            print(json.dumps({'action': 'block', 'message': message}))
            return 0
        print(json.dumps({'error': message}))
        return 1
    finally:
        if state:
            state.close()


if __name__ == '__main__':
    raise SystemExit(main())
