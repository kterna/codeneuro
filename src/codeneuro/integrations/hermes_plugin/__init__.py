"""Hermes directory plugin; only stdlib is imported into the Hermes process.

The actual worker runs in CodeNeuro's Python environment, avoiding dependencies
being installed into the live Hermes environment. No tools or approvals are replaced.
"""
import json
import os
from pathlib import Path
import subprocess

SUPPORTED = {'read_file', 'write_file', 'patch', 'terminal'}


def _invoke(event, kwargs):
    executable = os.environ.get('CODENEURO_PYTHON', '')
    root = Path(os.environ.get('CODENEURO_WORKSPACE', '')).expanduser().resolve()
    if not executable or not os.environ.get('CODENEURO_WORKSPACE'):
        raise ValueError('Set CODENEURO_PYTHON and CODENEURO_WORKSPACE explicitly')
    sid = kwargs.get('session_id') or kwargs.get('parent_session_id')
    if not sid:
        raise ValueError('Hermes hook has no host session_id')
    payload = {'hook_event_name': event, 'session_id': sid, 'cwd': str(root),
               'tool_name': kwargs.get('tool_name'), 'tool_input': kwargs.get('args') or {},
               'extra': {k: v for k, v in kwargs.items() if k not in ('session_id', 'parent_session_id', 'tool_name', 'args')}}
    process = subprocess.run([executable, '-m', 'codeneuro.integrations.hermes_hooks', '--workspace', str(root)],
                             input=json.dumps(payload, default=str), text=True, capture_output=True,
                             cwd=root, timeout=180, shell=False)
    if process.returncode != 0:
        raise RuntimeError('CodeNeuro worker failed')
    result = json.loads(process.stdout)
    if not isinstance(result, dict):
        raise ValueError('Invalid CodeNeuro worker response')
    return result


def register(ctx):
    def before(**kwargs):
        if kwargs.get('tool_name') not in SUPPORTED:
            return None
        try:
            return _invoke('pre_tool_call', kwargs)
        except Exception as exc:
            return {'action': 'block', 'message': 'CodeNeuro native preflight unavailable (' + type(exc).__name__ + ').'}

    def after(**kwargs):
        if kwargs.get('tool_name') not in SUPPORTED:
            return None
        try:
            _invoke('post_tool_call', kwargs)
        except Exception:
            # The transform hook below includes an explicit diagnostic if the
            # worker is still unavailable. An observed result is never replaced
            # by an invented pass/failure.
            return None
        return None

    def transform(**kwargs):
        if kwargs.get('tool_name') not in SUPPORTED:
            return None
        try:
            return _invoke('transform_tool_result', kwargs).get('result')
        except Exception as exc:
            return str(kwargs.get('result', '')) + '\n[CodeNeuro native context injection failed: ' + type(exc).__name__ + ']'

    def closed(**kwargs):
        try:
            _invoke('on_session_finalize', kwargs)
        except Exception:
            return None
        return None

    ctx.register_hook('pre_tool_call', before)
    ctx.register_hook('post_tool_call', after)
    ctx.register_hook('transform_tool_result', transform)
    # Hermes on_session_end is actually a per-message turn-finalizer event.
    # Only real host session boundaries close the pinned CodeNeuro session.
    ctx.register_hook('on_session_finalize', closed)
    ctx.register_hook('on_session_reset', closed)
