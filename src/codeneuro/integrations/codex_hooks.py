"""Codex 0.160 native command hooks, verified against installed wire schemas.

Read one JSON event from stdin, emit only hook JSON on stdout. The client bridge
owns authentication and pinned Hub sessions. This module never approves sandbox
permissions and never infers exit status from command output text.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys
from typing import Protocol

from codeneuro.paths import workspace_file


class NativeBridge(Protocol):
    def start_operation(self, kind: str, paths: list[str], request_id: str) -> dict: ...
    def end_operation(self, operation_id: str, status: str) -> dict: ...
    def context(self, path: str, request_id: str) -> dict: ...
    def preflight(self, files: list[str], plan: str, diff: str, request_id: str) -> dict: ...
    def record_test_run(self, **kwargs) -> dict: ...
    def cleanup(self, request_id: str) -> dict: ...


def stamp():
    return datetime.now(timezone.utc).isoformat()


def _key(*values):
    return hashlib.sha256('\0'.join(values).encode()).hexdigest()


def _output(event, text='', deny=None):
    specific = {'hookEventName': event}
    if text:
        specific['additionalContext'] = text
    if deny:
        specific.update(permissionDecision='deny', permissionDecisionReason=deny)
    return {'hookSpecificOutput': specific}


def command_parts(command: str, *, windows=False) -> list[str]:
    try:
        return [p.strip('"') if windows else p for p in shlex.split(command, posix=not windows)]
    except ValueError:
        return []


def classify_command(command: str, *, windows=False):
    """Conservative extraction. Opaque shell scripts must use the explicit MCP wrapper."""
    tokens = command_parts(command, windows=windows)
    if not tokens or re.search(r'[\n;|&<>`]', command) or '$(' in command:
        return {'kind': 'opaque', 'paths': [], 'argv': tokens}
    name = Path(tokens[0].replace('\\', '/')).name.lower()
    args = tokens[1:]
    if name in ('cat', 'type', 'get-content', 'gc', 'head', 'tail', 'more'):
        paths = []
        skip = False
        for token in args:
            if skip:
                skip = False
                continue
            if token in ('-n', '-c', '--lines', '--bytes', '-totalcount', '-tail'):
                skip = True
            elif not token.startswith('-'):
                paths.append(token)
        return {'kind': 'read', 'paths': paths, 'argv': tokens}
    if name == 'sed':
        writing = any(x == '-i' or x.startswith('-i') or x == '--in-place' for x in args)
        paths = [args[-1]] if args and not args[-1].startswith('-') else []
        return {'kind': 'write' if writing else 'read', 'paths': paths, 'argv': tokens}
    if name in ('rg', 'grep'):
        # The final explicit existing path is resolved by the handler. A regex is
        # never represented as proof that a corresponding file was accessed.
        return {'kind': 'search', 'paths': [args[-1]] if args else [], 'argv': tokens}
    is_test = (name in ('pytest', 'pytest.exe') or
               (name in ('python', 'python3', 'python.exe', 'py') and '-m' in args and 'pytest' in args) or
               (name in ('npm', 'npm.cmd', 'pnpm', 'pnpm.cmd', 'yarn', 'cargo', 'dotnet', 'go') and 'test' in args))
    if is_test:
        return {'kind': 'test', 'paths': [t.split('::', 1)[0] for t in args
                                         if not t.startswith('-') and (t.endswith(('.py', '.js', '.ts', '.csproj')) or '/' in t or '\\' in t)],
                'argv': tokens}
    if name in ('pwd', 'get-location') or (name == 'git' and args and args[0] in ('status', 'diff', 'log', 'show', 'branch', 'rev-parse', 'ls-files')
                                               and (args[0] != 'branch' or len(args) == 1)):
        return {'kind': 'inspect', 'paths': [], 'argv': tokens}
    return {'kind': 'opaque', 'paths': [], 'argv': tokens}


def patch_paths(patch):
    paths = []
    for line in patch.splitlines():
        for prefix in ('*** Update File: ', '*** Add File: ', '*** Delete File: ', '*** Move to: '):
            if line.startswith(prefix):
                paths.append(line[len(prefix):])
        if line.startswith(('+++ ', '--- ')):
            path = line[4:].split('\t', 1)[0]
            if path == '/dev/null':
                continue
            paths.append(path[2:] if path.startswith(('a/', 'b/')) else path)
    return list(dict.fromkeys(paths))


class HookState:
    """Small local journal; no tokens, full transcripts or arbitrary tool output."""
    def __init__(self, root):
        folder = root / '.codeneuro'
        if folder.is_symlink():
            raise ValueError('Native hook state directory cannot be a symlink.')
        folder.mkdir(exist_ok=True)
        path = folder / 'native-hooks.sqlite3'
        if path.is_symlink():
            raise ValueError('Native hook journal cannot be a symlink.')
        self.conn = sqlite3.connect(path, timeout=10)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,host_session TEXT,paths TEXT,kind TEXT,started_at TEXT)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS files(host_session TEXT,path TEXT,PRIMARY KEY(host_session,path))')
        self.conn.execute('CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,operation_id TEXT NOT NULL)')

    def remember(self, sid, call, paths, kind):
        with self.conn:
            self.conn.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?)', (_key(sid, call), sid, json.dumps(paths), kind, stamp()))
            self.conn.executemany('INSERT OR IGNORE INTO files VALUES(?,?)', [(sid, p) for p in paths])

    def paths(self, sid):
        return [r[0] for r in self.conn.execute('SELECT path FROM files WHERE host_session=? ORDER BY path LIMIT 500', (sid,))]

    def event(self, sid, call):
        row = self.conn.execute('SELECT paths,kind,started_at FROM events WHERE id=?', (_key(sid, call),)).fetchone()
        return {'paths': json.loads(row[0]), 'kind': row[1], 'started_at': row[2]} if row else None

    def close(self):
        self.conn.close()

    def set_operation(self, sid, call, operation_id):
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO operations VALUES(?,?)', (_key(sid, call), operation_id))

    def operation(self, sid, call):
        row = self.conn.execute('SELECT operation_id FROM operations WHERE id=?', (_key(sid, call),)).fetchone()
        return row[0] if row else None

    def clear_operation(self, sid, call):
        with self.conn:
            self.conn.execute('DELETE FROM operations WHERE id=?', (_key(sid, call),))


def terminal_evidence(event, root):
    """Only an exact host-authored terminal record supplies argv and exit_code.

PostToolUse.tool_response is only stdout in Codex 0.160. A rollout record may be
absent at hook time; that remains missing evidence, never a guessed success.
"""
    transcript = event.get('transcript_path')
    if not transcript:
        return None
    path = Path(transcript)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        return None
    with path.open('rb') as handle:
        head = handle.readline(1000000)
        try:
            first = json.loads(head)
        except (ValueError, UnicodeDecodeError):
            return None
        if first.get('type') != 'session_meta' or first.get('payload', {}).get('id') != event['session_id']:
            return None
        size = path.stat().st_size
        handle.seek(max(0, size - 8_000_000))
        if handle.tell():
            handle.readline()
        rows = handle.read(8_000_000).splitlines()
    for raw in reversed(rows):
        try:
            entry = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        payload = entry.get('payload', {})
        item = payload.get('item', {})
        if (entry.get('type') == 'event_msg' and payload.get('type') == 'item_completed'
                and payload.get('thread_id') == event['session_id'] and payload.get('turn_id') == event.get('turn_id')
                and item.get('id') == event['tool_use_id'] and item.get('type') == 'CommandExecution'
                and item.get('status') in ('completed', 'failed') and isinstance(item.get('exit_code'), int)
                and isinstance(item.get('command'), list) and payload.get('started_at_ms') is not None
                and payload.get('completed_at_ms') is not None):
            def iso(milliseconds):
                return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat()
            return {'command': item['command'], 'exit_code': item['exit_code'], 'stdout': item.get('stdout', ''),
                    'stderr': item.get('stderr', ''), 'started_at': iso(payload['started_at_ms']),
                    'finished_at': iso(payload['completed_at_ms'])}
    return None


def handle_event(event, *, workspace: Path, bridge: NativeBridge, state: HookState):
    root = workspace.resolve()
    cwd = Path(event.get('cwd', str(root))).resolve()
    if not cwd.is_relative_to(root):
        raise ValueError('Hook cwd is outside the configured workspace.')
    event_name = event.get('hook_event_name')
    sid = str(event.get('session_id', ''))
    if not sid:
        raise ValueError('Native host session_id is required.')
    if event_name == 'SessionEnd':
        result = bridge.cleanup(request_id='codex-close:' + sid)
        return {'systemMessage': 'CodeNeuro session cleanup recorded.' if result else 'CodeNeuro cleanup returned no receipt.'}
    if event_name not in ('PreToolUse', 'PostToolUse'):
        return {}
    call = str(event.get('tool_use_id', ''))
    if not call:
        raise ValueError('tool_use_id is required.')
    tool = event.get('tool_name', '')
    data = event.get('tool_input', {})
    # MCP wrappers already perform context/preflight themselves; do not recurse.
    if tool.lower().startswith(('mcp__', 'mcp.')):
        return {}
    if event_name == 'PostToolUse':
        previous = state.event(sid, call)
        try:
            if previous and previous['kind'] == 'test':
                evidence = terminal_evidence(event, root)
                if evidence and previous['paths']:
                    result = bridge.record_test_run(request_id='codex-test:' + call, paths=previous['paths'], **evidence)
                    return _output(event_name, 'CodeNeuro recorded native test evidence: ' + str(result.get('id', result)))
                return _output(event_name, 'CodeNeuro could not verify a terminal test record at this hook boundary; no test outcome was submitted. Use the CodeNeuro command tool for a receipt with actual exit status.')
            return {}
        finally:
            operation_id = state.operation(sid, call)
            if operation_id:
                bridge.end_operation(operation_id, status='failed' if event.get('tool_failed') else 'completed')
                state.clear_operation(sid, call)
    kind, candidates, patch, plan = 'inspect', [], '', ''
    if tool == 'Bash' and isinstance(data, dict):
        plan = data.get('command', '')
        classified = classify_command(plan, windows=os.name == 'nt')
        kind, candidates = classified['kind'], classified['paths']
        if kind == 'opaque':
            return _output(event_name, deny='CodeNeuro cannot determine this shell command\'s file scope. Use the CodeNeuro command tool with explicit affected paths for context and preflight.')
    elif isinstance(data, dict):
        candidates = [data[k] for k in ('file_path', 'path') if isinstance(data.get(k), str)]
        patch = data.get('patch', data.get('input', ''))
        if isinstance(patch, str):
            candidates.extend(patch_paths(patch))
        if candidates:
            kind = 'write' if any(k in data for k in ('content', 'patch', 'old_string', 'new_string', 'oldText', 'newText')) else 'read'
            plan = f'{tool} on declared file paths'
            if kind == 'write' and not patch:
                import difflib
                target = candidates[0]
                before = data.get('oldText', data.get('old_string', ''))
                after = data.get('newText', data.get('new_string', data.get('content', '')))
                patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                   fromfile='a/' + target, tofile='b/' + target))
    elif isinstance(data, str):
        patch, candidates, kind = data, patch_paths(data), 'write'
        plan = 'Apply the supplied patch'
    paths = []
    for candidate in candidates:
        path = Path(candidate)
        absolute = path if path.is_absolute() else cwd / path
        normalized = workspace_file(str(absolute), str(root))
        if kind == 'search' and not absolute.is_file():
            continue
        if absolute.is_dir():
            continue
        if normalized not in paths:
            paths.append(normalized)
    if kind == 'test':
        paths = list(dict.fromkeys(paths + state.paths(sid)))
    if len(paths) > 64:
        return _output(event_name, deny='This native call touches more than 64 paths. Split the operation or use the explicit CodeNeuro command wrapper.')
    state.remember(sid, call, paths, kind)
    operation = bridge.start_operation(kind=kind, paths=paths, request_id='native-operation:' + call)
    operation_id = operation.get('id') or operation['operation_id']
    state.set_operation(sid, call, operation_id)
    contexts = []
    try:
        for path in paths:
            response = bridge.context(path, request_id='codex-context:' + _key(call, path))
            contexts.append(f"CodeNeuro receipt {response.get('delivery_id', 'missing')} for {path}\n{response.get('rendered_markdown', '')}")
        if kind == 'write':
            if not paths:
                raise ValueError('The native modification did not expose paths; use the CodeNeuro edit tool.')
            result = bridge.preflight(files=paths, plan=plan, diff=patch, request_id='codex-preflight:' + call)
            if result.get('decision') != 'allow':
                bridge.end_operation(operation_id, status='failed')
                state.clear_operation(sid, call)
                return _output(event_name, '\n\n'.join(contexts), deny=f"CodeNeuro preflight requires {result.get('decision', 'review')}; receipt {result.get('id', 'missing')}. Inspect its evidence before changing files.")
    except Exception:
        bridge.end_operation(operation_id, status='failed')
        state.clear_operation(sid, call)
        raise
    return _output(event_name, '\n\n'.join(contexts)) if contexts else {}


def hook_config(python_executable, workspace, *, windows=None):
    """Generate project hooks only. Trust is reviewed separately in the host UI."""
    windows = os.name == 'nt' if windows is None else windows
    argv = [str(python_executable), '-m', 'codeneuro.integrations.codex_hooks', '--workspace', str(workspace)]
    command = subprocess.list2cmdline(argv) if windows else shlex.join(argv)
    return {'hooks': {name: [{'matcher': '.*', 'hooks': [{'type': 'command', 'command': command, 'timeout': 180}]}]
                      for name in ('PreToolUse', 'PostToolUse', 'SessionEnd')}}


def find_config(root):
    for directory in (root, *root.parents):
        candidate = directory / '.codeneuro.json'
        if candidate.is_file():
            return candidate
    raise ValueError('No .codeneuro.json found in this workspace or its parents.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--config', type=Path)
    parser.add_argument('--print-config', action='store_true')
    args = parser.parse_args(argv)
    if args.print_config:
        print(json.dumps(hook_config(sys.executable, args.workspace.resolve()), ensure_ascii=False, indent=2))
        return 0
    event = {}
    state = None
    try:
        raw = sys.stdin.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Hook input exceeds the 2 MB limit.')
        event = json.loads(raw)
        config = args.config or find_config(args.workspace.resolve())
        from codeneuro.client import create_native_bridge
        bridge = create_native_bridge(config_path=config, workspace=args.workspace.resolve(),
                                      host_session_id=event['session_id'], agent_client='Codex native hook')
        state = HookState(args.workspace.resolve())
        response = handle_event(event, workspace=args.workspace, bridge=bridge, state=state)
        print(json.dumps(response, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Do not print credentials, raw HTTP exceptions or full hook input.
        message = 'CodeNeuro hook failed (' + type(exc).__name__ + '). Inspect the local bridge configuration and Hub readiness.'
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
