"""A local workspace client for an explicitly trusted remote CodeNeuro Hub.

Repository configuration selects a project, never a credential destination.
File operations enforce the local workspace boundary. Test subprocesses execute
trusted repository code as the current user; they are not an OS security sandbox.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import uuid

import httpx

from .database import DomainError, Conflict
from .paths import relative_path

CONFIG_NAME = '.codeneuro.json'
MAX_FILE_BYTES = 2_000_000
MAX_TEST_OUTPUT_BYTES = 10_000_000
PRIVATE_DIRS = {'.git', '.ssh', '.aws', '.azure', '.gnupg', '.codex', '.hermes',
                '.codeneuro', '.kube', '.docker', '.claude', '.gcloud', 'secrets', 'credentials'}
PRIVATE_NAMES = {'credentials', 'credentials.json', 'credentials.toml', 'secrets.json',
                 'secrets.toml', 'auth.json', 'auth.toml', 'id_rsa', 'id_ed25519',
                 '.netrc', '.npmrc', '.pypirc', CONFIG_NAME}
PRIVATE_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.kdbx', '.jks', '.keystore'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix):
    return prefix + '_' + uuid.uuid4().hex


def _canonical_hub(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                any(c.isspace() for c in value)):
            raise ValueError
        port = parsed.port
    except (ValueError, TypeError):
        raise DomainError('Hub URL must be an absolute http(s) URL without userinfo, query or fragment.') from None
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    if port and port != (443 if parsed.scheme == 'https' else 80):
        host += ':' + str(port)
    path = parsed.path.rstrip('/')
    if any(part in ('.', '..') for part in path.split('/')) or '%' in path or '\\' in path:
        raise DomainError('Hub URL path must not contain traversal or escaped components.')
    return urlunsplit((parsed.scheme, host, path, '', ''))


def discover_config(start: str | Path | None = None, *, config_path: str | Path | None = None) -> dict:
    """Read nearest repository configuration without trusting its URL or sending data."""
    if config_path is not None:
        found = Path(config_path).expanduser().absolute()
    else:
        current = Path(start or Path.cwd()).expanduser().absolute()
        if current.is_file():
            current = current.parent
        found = next((p / CONFIG_NAME for p in (current, *current.parents) if (p / CONFIG_NAME).exists()), None)
        if found is None:
            raise DomainError('No .codeneuro.json found. Create project configuration or pass an explicit config path.')
    if found.is_symlink() or not found.is_file():
        raise DomainError('CodeNeuro configuration must be a regular file, not a symlink.')
    if found.stat().st_size > 65536:
        raise DomainError('CodeNeuro configuration exceeds 64 KiB.')
    try:
        data = json.loads(found.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError, OSError):
        raise DomainError('CodeNeuro configuration is not readable UTF-8 JSON.') from None
    if not isinstance(data, dict):
        raise DomainError('CodeNeuro configuration must be an object.')
    allowed = {'hub_url', 'project_id', 'active_task', 'token_env', 'schema_version'}
    if set(data) - allowed:
        raise DomainError('Unsupported configuration fields; credentials and trust must not be stored in repository config.')
    if not isinstance(data.get('project_id'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', data['project_id']):
        raise DomainError('Configuration requires a valid project_id.')
    data['hub_url'] = _canonical_hub(data.get('hub_url', ''))
    data['token_env'] = data.get('token_env', 'CODENEURO_TOKEN')
    if not isinstance(data['token_env'], str) or not re.fullmatch(r'CODENEURO_[A-Z0-9_]*TOKEN', data['token_env']):
        raise DomainError('token_env must name a dedicated CODENEURO_*TOKEN environment variable.')
    if data.get('active_task') is not None and not isinstance(data['active_task'], str):
        raise DomainError('active_task must be a task ID or null.')
    return {**data, 'config_path': str(found)}


def is_private_path(value: str) -> bool:
    parts = [p.casefold() for p in value.replace('\\', '/').split('/')]
    if any(p in PRIVATE_DIRS or p.startswith('.env') for p in parts):
        return True
    if '.config' in parts and any(p in {'gcloud', 'gh', 'op', 'sops'} for p in parts):
        return True
    name = parts[-1] if parts else ''
    return (name in PRIVATE_NAMES or name.endswith(tuple(PRIVATE_SUFFIXES)) or
            name.startswith(('credentials.', 'secrets.', 'id_rsa.', 'id_ed25519.')))


def _reparse(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


class RemoteClient:
    """Pinned authenticated RPC plus explicit local file/test operations.

    ``trusted_hub_url`` is an explicit launcher/user input, not a config field.
    ``transport`` exists for deterministic transport tests, never repository config.
    """
    def __init__(self, config: dict, workspace: str | Path, *, trusted_hub_url: str | None = None,
                 token: str | None = None, agent_client: str = 'CodeNeuro MCP sidecar',
                 debug: bool = False, timeout: float = 130, transport=None, host_session_id: str | None = None):
        configured = _canonical_hub(config.get('hub_url', ''))
        trusted = trusted_hub_url or os.environ.get('CODENEURO_HUB_URL')
        if not trusted:
            raise DomainError('Explicitly pin the trusted Hub with CODENEURO_HUB_URL or trusted_hub_url. Repository config alone cannot authorize sending credentials or code.', 'hub_trust_required', 403)
        if _canonical_hub(trusted) != configured:
            raise DomainError('Repository Hub URL differs from the explicitly trusted Hub. No credentials or code were sent.', 'hub_mismatch', 403)
        env_name = config.get('token_env', 'CODENEURO_TOKEN')
        if not isinstance(env_name, str) or not re.fullmatch(r'CODENEURO_[A-Z0-9_]*TOKEN', env_name):
            raise DomainError('Use a dedicated CODENEURO_*TOKEN environment variable.')
        secret = token if token is not None else os.environ.get(env_name)
        if not secret or '\n' in secret or '\r' in secret:
            raise DomainError('A dedicated client bearer token is required in ' + env_name + '.')
        root = Path(workspace).expanduser().absolute()
        if not root.is_dir() or _reparse(root):
            raise DomainError('Workspace must be an existing native directory, not a symlink or junction.')
        self.workspace = root.resolve()
        self.config = dict(config)
        self.project_id = config.get('project_id')
        if not isinstance(self.project_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', self.project_id):
            raise DomainError('A valid project_id is required.')
        self.agent_client = agent_client
        self.debug = debug
        self._token = secret
        self._http = httpx.Client(base_url=configured + '/', timeout=timeout,
                                  headers={'Authorization': 'Bearer ' + secret},
                                  follow_redirects=False, trust_env=False, transport=transport)
        self.session: dict | None = None
        self.receipts: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._host_session_id = host_session_id or os.environ.get('CODENEURO_HOST_SESSION_ID')
        self.agent_client = os.environ.get('CODENEURO_AGENT_CLIENT', self.agent_client)
        binding = [configured, self.project_id, config.get('active_task'), str(self.workspace), self._host_session_id, hashlib.sha256(secret.encode()).hexdigest()]
        self._store = _SessionStore(self.workspace, hashlib.sha256(json.dumps(binding).encode()).hexdigest()) if self._host_session_id else None

    def rpc(self, op: str, args: dict | None = None):
        try:
            response = self._http.post('api/client/rpc', json={'op': op, 'args': args or {}})
        except httpx.HTTPError as exc:
            raise DomainError('Hub request failed: ' + type(exc).__name__, 'hub_unavailable', 503) from None
        if 300 <= response.status_code < 400:
            raise DomainError('Hub redirects are refused to keep the bearer token pinned.', 'hub_redirect_refused', 502)
        try:
            data = response.json()
        except ValueError:
            raise DomainError('Hub returned an invalid JSON response.', 'hub_response_invalid', 502) from None
        if response.is_error:
            detail = data.get('detail', data.get('error', 'Hub rejected the request.')) if isinstance(data, dict) else 'Hub rejected the request.'
            message = detail if isinstance(detail, str) else json.dumps(detail)
            raise DomainError(message.replace(self._token, '[REDACTED]')[:4000], 'hub_rejected', response.status_code)
        if not isinstance(data, dict) or 'result' not in data:
            raise DomainError('Hub RPC response has no result envelope.', 'hub_response_invalid', 502)
        return data['result']

    def _git(self, *args):
        try:
            result = subprocess.run(['git', '-C', str(self.workspace), *args], capture_output=True,
                                    text=True, timeout=10, check=False)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    def _register_session(self):
        # Identity excludes remotes, which may embed credentials.
        common = self._git('rev-parse', '--path-format=absolute', '--git-common-dir')
        identity = hashlib.sha256((common or str(self.workspace)).encode()).hexdigest()
        result = self.rpc('start_session', {'project_id': self.project_id,
            'workspace_path': str(self.workspace), 'machine_name': socket.gethostname(),
            'platform': 'windows' if os.name == 'nt' else 'linux',
            'git_branch': self._git('rev-parse', '--abbrev-ref', 'HEAD') or '',
            'git_commit': self._git('rev-parse', 'HEAD'), 'repo_identity': identity,
            'task_id': self.config.get('active_task'), 'agent_client': self.agent_client, 'debug': self.debug})
        if not isinstance(result, dict) or not result.get('id') or result.get('project_id') != self.project_id:
            raise DomainError('Hub returned an invalid session identity.', 'hub_response_invalid', 502)
        return result

    def start_session(self):
        with self._lock:
            if self._store:
                with self._store.locked():
                    state = self._store.load()
                    previous = state.get('session')
                    if previous:
                        try:
                            current = self.rpc('session_status', {'session_id': previous['id']})
                        except DomainError as exc:
                            if exc.status not in (404, 409):
                                raise  # A transient observation failure must not create a duplicate session.
                            current = None
                        if current and current.get('project_id') == self.project_id and current.get('state', 'active') == 'active':
                            self.session = current
                            self.receipts.update(state.get('receipts', {}))
                            state['session'] = current
                            self._store.save(state)
                            return current
                    self.session = self._register_session()
                    self.receipts.clear()
                    self._store.save({'session': self.session, 'receipts': {}})
                    return self.session
            if self.session is None:
                self.session = self._register_session()
            return self.session

    def _retain_receipt(self, receipt, result):
        self.receipts[receipt] = result
        if self._store:
            with self._store.locked():
                state = self._store.load()
                if state.get('session', {}).get('id') != self.session['id']:
                    raise Conflict('Host session changed while context was retrieved; request context again.')
                receipts = state.setdefault('receipts', {})
                receipts[receipt] = {'session_id': self.session['id'], 'delivery_id': receipt,
                                     'file_path': result.get('file_path')}
                state['receipts'] = dict(list(receipts.items())[-2000:])
                self._store.save(state)

    @property
    def session_id(self):
        return self.start_session()['id']

    def path(self, value: str, *, allow_missing: bool = False) -> tuple[str, Path]:
        if not isinstance(value, str) or not value:
            raise DomainError('A workspace-relative file path is required.')
        native = Path(value).expanduser()
        if native.is_absolute():
            try:
                value = native.relative_to(self.workspace).as_posix()
            except ValueError:
                raise DomainError('File path is outside the workspace.') from None
        rel = relative_path(value)
        if os.name == 'nt' and any(':' in part or part.endswith(('.', ' ')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part) for part in rel.split('/')):
            raise DomainError('Windows device names, alternate data streams and normalized aliases are excluded.')
        if is_private_path(rel):
            raise DomainError('Credential and client-private locations are excluded from file tools and indexing.', 'private_path', 403)
        current = self.workspace
        parts = rel.split('/')
        for i, part in enumerate(parts):
            current = current / part
            if current.exists() or current.is_symlink():
                if _reparse(current):
                    raise DomainError('Symlinks and filesystem junctions are excluded from workspace operations.', 'unsafe_path', 403)
                if i < len(parts) - 1 and not current.is_dir():
                    raise DomainError('A file path parent is not a directory.')
            elif i < len(parts) - 1 or not allow_missing:
                raise DomainError('Workspace file or parent directory does not exist.', 'not_found', 404)
        if not current.resolve().is_relative_to(self.workspace):
            raise DomainError('File path resolves outside the workspace.', 'unsafe_path', 403)
        if current.exists() and not current.is_file():
            raise DomainError('File tools only operate on regular files.')
        return rel, current

    @contextmanager
    def _parent(self, rel):
        """Pin POSIX directory descriptors so a swapped symlink cannot redirect I/O."""
        if os.name == 'nt':
            yield None
            return
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(self.workspace, flags)
        try:
            for part in rel.split('/')[:-1]:
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd);fd = next_fd
            yield fd
        finally:
            os.close(fd)

    def _read(self, rel, path, *, allow_missing=False):
        with self._parent(rel) as parent:
            try:
                if parent is None:
                    self.path(rel, allow_missing=allow_missing)
                    stream = path.open('rb')
                else:
                    fd = os.open(path.name, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0), dir_fd=parent)
                    stream = os.fdopen(fd, 'rb')
            except FileNotFoundError:
                if allow_missing:
                    return None
                raise DomainError('Workspace file does not exist.', 'not_found', 404) from None
            with stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                    raise DomainError('File must be regular and at most 2 MB.')
                data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise DomainError('File exceeds the 2 MB read limit.')
        if b'\0' in data:
            raise DomainError('Binary files are not supported by text tools.')
        if re.search(rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----', data):
            raise DomainError('Private-key material is excluded from file tools.', 'private_path', 403)
        try:
            data.decode('utf-8')
        except UnicodeError:
            raise DomainError('File is not UTF-8 text.') from None
        return data

    @contextmanager
    def operation(self, kind: str, paths: list[str]):
        session_id = self.session_id
        result = self.rpc('start_operation', {'session_id': session_id, 'kind': kind,
                          'paths': paths, 'request_id': _uid('operation')})
        operation_id = result.get('operation_id') or result.get('id')
        if not operation_id:
            raise DomainError('Hub did not establish a safe operation boundary.', 'hub_response_invalid', 502)
        status = 'failed'
        try:
            yield operation_id
            status = 'completed'
        finally:
            # An end failure is surfaced; the server must not infer task safety from silence.
            self.rpc('end_operation', {'session_id': session_id, 'operation_id': operation_id, 'status': status})

    def context(self, file_path: str, *, request_id: str | None = None, max_chars: int = 24000):
        rel, _ = self.path(file_path, allow_missing=True)
        result = self.rpc('context', {'session_id': self.session_id, 'file_path': rel,
                          'request_id': request_id or _uid('read'), 'max_chars': max_chars})
        receipt = result.get('delivery_id') if isinstance(result, dict) else None
        if not receipt:
            raise DomainError('Hub context response is missing a delivery receipt.', 'hub_response_invalid', 502)
        self._retain_receipt(receipt, result)
        return result

    def read_file(self, file_path: str, *, start_line: int = 1, end_line: int | None = None):
        if isinstance(start_line, bool) or start_line < 1 or (end_line is not None and end_line < start_line):
            raise DomainError('Line range must start at one and be ordered.')
        with self._lock:
            rel, path = self.path(file_path)
            with self.operation('read', [rel]):
                context = self.context(rel)
                data = self._read(rel, path)
                all_lines = data.decode('utf-8').splitlines(keepends=True)
                return {'path': rel, 'sha256': hashlib.sha256(data).hexdigest(),
                        'start_line': start_line, 'end_line': min(end_line or len(all_lines), len(all_lines)),
                        'total_lines': len(all_lines), 'content': ''.join(all_lines[start_line - 1:end_line]),
                        'context': context, 'delivery_id': context['delivery_id']}

    def edit_file(self, file_path: str, new_content: str, expected_sha256: str, plan: str):
        """Version-check, assess the real unified diff, then atomically replace one file."""
        if not isinstance(new_content, str) or '\0' in new_content or len(new_content.encode('utf-8')) > MAX_FILE_BYTES:
            raise DomainError('New content must be bounded UTF-8 text without NUL.')
        if not plan.strip():
            raise DomainError('Explain the intended change for preflight assessment.')
        with self._lock:
            rel, path = self.path(file_path, allow_missing=True)
            with self.operation('edit', [rel]):
                before = self._read(rel, path, allow_missing=True)
                digest = hashlib.sha256(before).hexdigest() if before is not None else 'missing'
                if digest != expected_sha256:
                    raise Conflict('File changed since it was read; read current content before editing.')
                context = self.context(rel)
                old_text = before.decode('utf-8') if before is not None else ''
                diff = ''.join(difflib.unified_diff(old_text.splitlines(keepends=True), new_content.splitlines(keepends=True),
                                                  fromfile='a/' + rel if before is not None else '/dev/null', tofile='b/' + rel))
                assessment = self.rpc('preflight', {'session_id': self.session_id, 'request_id': _uid('preflight'),
                                      'files': [rel], 'plan': plan, 'diff': diff})
                if assessment.get('decision') != 'allow' or assessment.get('stale'):
                    return {'status': 'blocked' if assessment.get('decision') == 'block' else 'review_required',
                            'path': rel, 'written': False, 'preflight': assessment, 'context': context}
                if self._read(rel, path, allow_missing=True) != before:
                    raise Conflict('File changed while the plan was assessed; no edit was applied.')
                self._atomic_write(rel, path, new_content.encode('utf-8'), before)
                return {'status': 'edited', 'written': True, 'path': rel, 'sha256': hashlib.sha256(new_content.encode()).hexdigest(),
                        'preflight': assessment, 'context': context, 'delivery_id': context['delivery_id'], 'diff': diff}

    def _atomic_write(self, rel, path, data, before):
        self.path(rel, allow_missing=True)
        name = '.codeneuro-edit-' + uuid.uuid4().hex
        with self._parent(rel) as parent:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            target = path.parent / name if parent is None else name
            fd = os.open(target, flags, 0o600, **({} if parent is None else {'dir_fd': parent}))
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(data);output.flush();os.fsync(output.fileno())
                # Preserve executable bits of an existing source file.
                if before is not None:
                    mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
                    os.chmod(target, mode, **({} if parent is None else {'dir_fd': parent}))
                self.path(rel, allow_missing=True)
                if self._read(rel, path, allow_missing=True) != before:
                    raise Conflict('File changed before atomic replacement; no edit was applied.')
                if parent is None:
                    os.replace(target, path)
                else:
                    os.replace(name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
            finally:
                try:
                    os.unlink(target, **({} if parent is None else {'dir_fd': parent}))
                except FileNotFoundError:
                    pass

    @staticmethod
    def _kill_tree(process):
        if process.poll() is not None and os.name == 'nt':
            return
        if os.name == 'nt':
            # taskkill /T terminates descendants even when they opened their own handles.
            try:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, timeout=10, check=False)
            except (OSError, subprocess.SubprocessError):
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=5)

    def _redact(self, value: str):
        secrets = {self._token}
        for name, content in os.environ.items():
            if re.search(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|PRIVATE_KEY|AUTHORIZATION', name, re.I) and len(content) >= 8:
                secrets.add(content)
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, '[REDACTED]')
        return value

    def run_tests(self, command: list[str], paths: list[str], *, timeout_seconds: int = 120):
        """Execute actual argv in the workspace, bound resources, and record actual output.

        Like any local test runner, this executes trusted repository code with user
        permissions. The tool does not pretend cwd is an OS filesystem sandbox.
        """
        if (not isinstance(command, list) or not 1 <= len(command) <= 200 or
                any(not isinstance(arg, str) or not arg or '\0' in arg or len(arg) > 10000 for arg in command)):
            raise DomainError('Tests require a bounded non-empty argv list; shell strings are unsupported.')
        if not 1 <= timeout_seconds <= 900:
            raise DomainError('Test timeout must be between 1 and 900 seconds.')
        if any(self._redact(arg) != arg for arg in command):
            raise DomainError('Do not pass credentials in test argv.')
        executable = Path(command[0]).name.lower()
        if executable in {'sh', 'bash', 'zsh', 'fish', 'cmd', 'cmd.exe', 'powershell', 'powershell.exe', 'pwsh', 'pwsh.exe'}:
            raise DomainError('Invoke the actual test executable with argv; shell interpreters are not supported.')
        normalized = [self.path(path, allow_missing=True)[0] for path in paths]
        if not normalized or len(normalized) > 500:
            raise DomainError('Supply between one and 500 affected workspace paths.')
        # Protect against accidentally running a test file from a different workspace.
        for arg in command[1:]:
            value = arg.partition('=')[2] if arg.startswith('-') and '=' in arg else arg
            if Path(value).is_absolute():
                self.path(value)
        request_id = _uid('test')
        with self._lock, self.operation('test', normalized):
            contexts = [self.context(path) for path in normalized]
            started = _now()
            env = {key: value for key, value in os.environ.items()
                   if not re.search(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|PRIVATE_KEY|AUTHORIZATION|PROXY', key, re.I)
                   and key not in {'CODENEURO_HUB_URL', 'PYTHONSTARTUP', 'PYTHONINSPECT'}}
            timed_out, output_limited = False, False
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                try:
                    process = subprocess.Popen(command, cwd=self.workspace, env=env, stdin=subprocess.DEVNULL,
                                               stdout=stdout, stderr=stderr, shell=False,
                                               **({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}))
                except OSError as exc:
                    raise DomainError('Could not start test executable: ' + type(exc).__name__) from None
                deadline = time.monotonic() + timeout_seconds
                try:
                    while process.poll() is None:
                        if time.monotonic() >= deadline:
                            timed_out = True;self._kill_tree(process);break
                        if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > MAX_TEST_OUTPUT_BYTES:
                            output_limited = True;self._kill_tree(process);break
                        time.sleep(.05)
                    exit_code = process.wait()
                    if os.name != 'nt':
                        self._kill_tree(process)  # Reap leftover same-group descendants after launcher exits.
                except BaseException:
                    self._kill_tree(process)
                    raise
                stdout.seek(0);stderr.seek(0)
                out = self._redact(stdout.read(MAX_TEST_OUTPUT_BYTES).decode('utf-8', errors='replace'))
                err = self._redact(stderr.read(MAX_TEST_OUTPUT_BYTES).decode('utf-8', errors='replace'))
            finished = _now()
            # Keep bounded, redacted full output locally. This directory is never indexed.
            artifact_dir = self.workspace / '.codeneuro' / 'test-runs'
            for directory in [artifact_dir.parent, artifact_dir]:
                if directory.exists() and (_reparse(directory) or not directory.is_dir()):
                    raise DomainError('Private test artifact directory must not be a symlink or junction.')
                directory.mkdir(mode=0o700, exist_ok=True)
            artifact = artifact_dir / (request_id + '.json')
            payload = {'command': command, 'exit_code': exit_code, 'stdout': out, 'stderr': err,
                       'started_at': started, 'finished_at': finished, 'paths': normalized,
                       'timed_out': timed_out, 'output_limited': output_limited}
            fd = os.open(artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False)
            def excerpt(value):
                if len(value) <= 90000:
                    return value
                return value[:45000] + '\n[output excerpt; full bounded output retained locally]\n' + value[-45000:]
            report = {key: payload[key] for key in ('command', 'exit_code', 'started_at', 'finished_at', 'paths')}
            report.update(session_id=self.session_id, request_id=request_id, stdout=excerpt(out), stderr=excerpt(err))
            try:
                recorded = self.rpc('test_run', report)
            except DomainError as exc:
                return {**report, 'status': 'recording_failed', 'recording_error': str(exc),
                        'artifact': str(artifact), 'timed_out': timed_out, 'output_limited': output_limited,
                        'contexts': contexts, 'recorded': False}
            return {**report, 'status': 'completed', 'recorded': True, 'test_run': recorded,
                    'artifact': str(artifact), 'timed_out': timed_out, 'output_limited': output_limited,
                    'contexts': contexts}

    def index_workspace(self):
        """Build bounded static code metadata locally; never ask Hub to scan native paths."""
        from .indexing import build_manifest
        session = self.start_session()
        manifest = build_manifest(self.workspace)
        manifest['files'] = [item for item in manifest.get('files', []) if not is_private_path(item['path'])]
        return self.rpc('index_manifest', {'worktree_id': session['worktree_id'], 'manifest': manifest})

    def rate_rule(self, delivery_id: str, rule_id: str, score: int, reason: str):
        if not self.debug:
            raise DomainError('Debug feedback is disabled for this client.', 'debug_disabled', 403)
        self.start_session()  # Restore native-hook receipts for the same pinned host session.
        if delivery_id not in self.receipts:
            raise DomainError('Rate only an actual receipt observed by this client.')
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 5:
            raise DomainError('Score must be an integer from zero to five.')
        return self.rpc('feedback', {'session_id': self.session_id, 'delivery_id': delivery_id,
                        'rule_id': rule_id, 'score': score, 'reason': reason})

    def cleanup(self, *, close: bool = True, request_id: str = 'sidecar-cleanup'):
        with self._lock, (self._store.locked() if self._store else nullcontext()):
            state = self._store.load() if self._store else {}
            previous = state.get('last_cleanup')
            if previous and previous.get('request_id') == request_id:
                return previous['result']
            session = state.get('session') if self._store else self.session
            if session is None:
                return {'status': 'not_started'}
            result = self.rpc('cleanup', {'session_id': session['id'], 'request_id': request_id, 'close': close})
            if close:
                if self._store:
                    self._store.save({'session': None, 'receipts': {}, 'last_cleanup': {'request_id': request_id, 'result': result}})
                self.session = None
                self.receipts.clear()
            return result

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class _SessionStore:
    """Local IDs and receipt references, never bearer tokens or code content."""
    def __init__(self, workspace: Path, binding_key: str):
        self.directory = workspace / '.codeneuro' / 'native-sessions'
        for directory in (self.directory.parent, self.directory):
            if directory.exists() and (_reparse(directory) or not directory.is_dir()):
                raise DomainError('Native session state must be in a real private workspace directory.')
            directory.mkdir(mode=0o700, exist_ok=True)
        self.path = self.directory / (binding_key + '.json')
        self.lock_path = self.directory / (binding_key + '.lock')

    @contextmanager
    def locked(self):
        for path in (self.directory.parent, self.directory, self.path, self.lock_path):
            if path.exists() and _reparse(path):
                raise DomainError('Symlink/junction found in native session state.')
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b'\0')
                deadline = time.monotonic() + 150
                while True:
                    try:
                        os.lseek(fd, 0, os.SEEK_SET);msvcrt.locking(fd, msvcrt.LK_NBLCK, 1);break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise Conflict('Native session is busy; retry the same operation.') from None
                        time.sleep(.05)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            if os.name == 'nt':
                import msvcrt
                try:
                    os.lseek(fd, 0, os.SEEK_SET);msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def load(self):
        if not self.path.exists():
            return {}
        if self.path.stat().st_size > 2_000_000:
            raise DomainError('Native session state exceeds its size bound.')
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError):
            raise DomainError('Native session state is unreadable; preserve it for diagnosis before resetting.') from None
        if not isinstance(value, dict):
            raise DomainError('Native session state must be an object.')
        return value

    def save(self, state):
        temp = self.directory / ('.state-' + uuid.uuid4().hex)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(state, stream, ensure_ascii=False)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)


class NativeBridge:
    """Narrow interface used by verified native host hooks across subprocesses."""
    def __init__(self, client: RemoteClient):
        self.client = client

    def context(self, path, request_id):
        return self.client.context(path, request_id=request_id)

    def preflight(self, files, plan, diff, request_id):
        paths = [self.client.path(path, allow_missing=True)[0] for path in files]
        return self.client.rpc('preflight', {'session_id': self.client.session_id, 'files': paths,
                               'plan': plan, 'diff': diff, 'request_id': request_id})

    def record_test_run(self, **evidence):
        evidence['paths'] = [self.client.path(path, allow_missing=True)[0] for path in evidence['paths']]
        # Native hook output is actual host event data, never an inferred pass/fail.
        evidence['stdout'] = self.client._redact(evidence.get('stdout', ''))
        evidence['stderr'] = self.client._redact(evidence.get('stderr', ''))
        return self.client.rpc('test_run', {**evidence, 'session_id': self.client.session_id})

    def start_operation(self, kind, paths, request_id):
        paths = [self.client.path(path, allow_missing=True)[0] for path in paths]
        return self.client.rpc('start_operation', {'session_id': self.client.session_id, 'kind': kind,
                               'paths': paths, 'request_id': request_id})

    def end_operation(self, operation_id, status):
        return self.client.rpc('end_operation', {'session_id': self.client.session_id,
                               'operation_id': operation_id, 'status': status})

    def cleanup(self, request_id):
        return self.client.cleanup(request_id=request_id)

    def close(self):
        self.client.close()


def create_native_bridge(config_path: Path, workspace: Path, host_session_id: str, agent_client: str):
    if not host_session_id or len(host_session_id) > 2000:
        raise DomainError('A bounded actual host session ID is required for native hooks.')
    config = discover_config(config_path=config_path)
    return NativeBridge(RemoteClient(config, workspace, agent_client=agent_client,
                                     debug=True, host_session_id=host_session_id))
