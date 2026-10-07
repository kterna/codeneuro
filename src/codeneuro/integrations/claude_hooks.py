"""Claude Code native hooks, verified against CLI 2.1.220 and sdk-tools.d.ts.

Claude shares PreToolUse/PostToolUse field names with Codex; failure events are
separate. Native BashOutput has no exit_code, so test execution remains an MCP
sidecar operation unless the host supplies a verifiable terminal record.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from .codex_hooks import HookState, find_config, handle_event, _output


def handle_claude(event, *, workspace, bridge, state):
    translated = dict(event)
    if event.get('hook_event_name') == 'PostToolUseFailure':
        translated.update(hook_event_name='PostToolUse', tool_failed=True)
    # Never parse another host's transcript using Codex's rollout schema.
    translated['transcript_path'] = None
    response = handle_event(translated, workspace=workspace, bridge=bridge, state=state)
    if event.get('hook_event_name') == 'PostToolUseFailure':
        message = response.get('hookSpecificOutput', {}).get('additionalContext')
        return {'systemMessage': message} if message else {}
    return response


def claude_config(python_executable, workspace, *, windows=None):
    windows = os.name == 'nt' if windows is None else windows
    args = [str(python_executable), '-m', 'codeneuro.integrations.claude_hooks', '--workspace', str(workspace)]
    command = subprocess.list2cmdline(args) if windows else shlex.join(args)
    hooks = {}
    for name in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure'):
        hooks[name] = [{'matcher': 'Read|Edit|Write|Bash', 'hooks': [{'type': 'command', 'command': command, 'timeout': 180}]}]
    hooks['SessionEnd'] = [{'hooks': [{'type': 'command', 'command': command, 'timeout': 180}]}]
    return {'hooks': hooks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--config', type=Path)
    parser.add_argument('--print-config', action='store_true')
    args = parser.parse_args(argv)
    root = args.workspace.resolve()
    if args.print_config:
        print(json.dumps(claude_config(sys.executable, root), indent=2, ensure_ascii=False))
        return 0
    event, state = {}, None
    try:
        raw = sys.stdin.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Hook input exceeds 2 MB')
        event = json.loads(raw)
        from codeneuro.client import create_native_bridge
        bridge = create_native_bridge(config_path=args.config or find_config(root), workspace=root,
                                      host_session_id=event['session_id'], agent_client='Claude Code')
        state = HookState(root)
        print(json.dumps(handle_claude(event, workspace=root, bridge=bridge, state=state), ensure_ascii=False))
        return 0
    except Exception as exc:
        message = 'CodeNeuro Claude hook failed (' + type(exc).__name__ + '). Check the trusted Hub and workspace configuration.'
        if event.get('hook_event_name') == 'PreToolUse':
            print(json.dumps(_output('PreToolUse', deny=message)))
            return 0
        print(message, file=sys.stderr)
        return 1
    finally:
        if state:
            state.close()


if __name__ == '__main__':
    raise SystemExit(main())
