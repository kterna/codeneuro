"""Scoped remote snapshots with observable lag and cancellable polling.

The authenticated export_rules RPC is authoritative. Local SSE availability is
not assumed; a bounded poll always reconciles the complete scoped snapshot.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Callable

from .database import Conflict, DomainError
from .exporter import RuleExporter, slugify
from .models import Lifecycle, Rule, RuleStatus


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _write(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.sync-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _lease(path):
    """One watcher owns one worktree, across processes on Windows and Unix."""
    if path.is_symlink():
        raise DomainError('Sync lock cannot be a symlink.')
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'\0'); stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise Conflict('Another sync watcher owns this worktree.') from exc
            release = lambda: (stream.seek(0), msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1))
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise Conflict('Another sync watcher owns this worktree.') from exc
            release = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        try:
            yield
        finally:
            release()


class StaticSync:
    """Synchronize a RemoteClient's actual current task into managed local files.

    ``status_callback`` receives safe status dicts suitable for a CLI/desktop UI.
    It is never given the token, rule content or raw transport exceptions.
    """
    def __init__(self, client, *, formats=('cursor', 'claude'), poll_interval=2.0,
                 max_backoff=30.0, status_callback: Callable[[dict], None] | None = None,
                 invalidate_on_stop=True):
        if not 0.05 <= poll_interval <= 60 or not poll_interval <= max_backoff <= 300:
            raise DomainError('Polling must be 0.05 to 60 seconds; backoff must be polling interval to 300 seconds.')
        if isinstance(formats, str):
            formats = ('cursor', 'claude') if formats == 'both' else (formats,)
        if not formats or len(set(formats)) != len(formats) or set(formats) - {'cursor', 'claude'}:
            raise DomainError('Select cursor, claude or both export formats.')
        self.client, self.formats = client, tuple(formats)
        self.root = Path(client.workspace)
        self.state_dir = self.root / '.codeneuro'
        if self.state_dir.is_symlink():
            raise DomainError('Sync state directory cannot be a symlink.')
        self.state_dir.mkdir(exist_ok=True)
        self.status_file = self.state_dir / 'sync-status.json'
        self.managed_file = self.state_dir / 'sync-managed.json'
        for path in (self.status_file, self.managed_file):
            if path.is_symlink():
                raise DomainError('Sync state files cannot be symlinks.')
        self.poll_interval, self.max_backoff = float(poll_interval), float(max_backoff)
        self.callback = status_callback
        self.invalidate_on_stop = invalidate_on_stop
        self._fingerprint = None
        self._last_success = None
        self._last_success_monotonic = None
        self._started = time.monotonic()
        self._retry = self.poll_interval
        self._mutex = threading.RLock()
        self._watching = False
        self._status = {'state': 'starting', 'project_id': client.project_id, 'transport': 'poll',
                        'poll_interval_seconds': self.poll_interval, 'formats': list(self.formats),
                        'last_success_at': None, 'last_attempt_at': None, 'lag_seconds': None,
                        'task_id': None, 'binding_revision': None, 'rule_count': 0,
                        'managed_snapshots_valid': False, 'next_retry_seconds': 0,
                        'error': None, 'watching': False}

    def _publish_status(self, **changes):
        elapsed = time.monotonic() - (self._last_success_monotonic or self._started)
        self._status.update(changes, last_success_at=self._last_success, lag_seconds=round(max(0, elapsed), 3),
                            updated_at=_stamp(), watching=self._watching)
        _write(self.status_file, self._status)
        if self.callback:
            self.callback(dict(self._status))
        return dict(self._status)

    def status(self):
        return dict(self._status)

    def _snapshot(self):
        session = self.client.start_session()
        response = self.client.rpc('export_rules', {'session_id': session['id']})
        if not isinstance(response, dict) or response.get('project_id') != self.client.project_id:
            raise DomainError('Hub snapshot belongs to another project.', 'invalid_snapshot')
        revision, task = response.get('binding_revision'), response.get('task_id')
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise DomainError('Hub snapshot has no valid binding revision.', 'invalid_snapshot')
        if task is not None and not isinstance(task, str):
            raise DomainError('Hub snapshot task is invalid.', 'invalid_snapshot')
        raw = response.get('rules')
        if not isinstance(raw, list) or len(raw) > 100000:
            raise DomainError('Hub snapshot has an invalid rule list.', 'invalid_snapshot')
        rules, ids = [], set()
        for value in raw:
            rule = Rule.model_validate(value)
            if rule.project_id != self.client.project_id or rule.id in ids:
                raise DomainError('Hub snapshot contains mixed projects or duplicate rules.', 'invalid_snapshot')
            if rule.status != RuleStatus.ACTIVE:
                raise DomainError('Hub snapshot contains inactive rules.', 'invalid_snapshot')
            if rule.lifecycle == Lifecycle.SHORT_TERM and (not task or rule.task_id != task):
                raise DomainError('Hub snapshot contains rules from another task.', 'invalid_snapshot')
            if rule.lifecycle == Lifecycle.LONG_TERM and rule.task_id:
                raise DomainError('Hub snapshot contains a task-bound permanent contract.', 'invalid_snapshot')
            ids.add(rule.id); rules.append(rule)
        rules.sort(key=lambda r: (r.priority.rank, r.id))
        # Feedback/hit counters do not change exported instructions. Ignore them
        # so live delivery traffic cannot cause an endless rewrite loop.
        payload = {'project_id': self.client.project_id, 'task_id': task, 'binding_revision': revision,
                   'rules': [{k: r.model_dump(mode='json')[k] for k in
                              ('id', 'version', 'title', 'content_points', 'scope_patterns', 'priority', 'lifecycle', 'status', 'task_id')}
                             for r in rules]}
        return payload, rules, _digest(payload)

    def _owned_manifest(self):
        directory = self.root / '.cursor' / 'rules'
        for path in (self.root / '.cursor', directory, directory / '.codeneuro-manifest.json'):
            if path.is_symlink():
                raise DomainError('Managed export paths cannot be symlinks.')
        manifest = directory / '.codeneuro-manifest.json'
        if not manifest.exists():
            return set()
        if manifest.stat().st_size > 4_000_000:
            raise DomainError('Managed export manifest exceeds its size limit.')
        data = json.loads(manifest.read_text(encoding='utf-8'))
        files = data.get('files')
        if not isinstance(files, list):
            raise DomainError('Invalid managed export manifest.')
        for name in files:
            if not isinstance(name, str) or Path(name).name != name or not name.startswith('codeneuro-') or not name.endswith('.mdc'):
                raise DomainError('Invalid managed export filename.')
            if (directory / name).is_symlink():
                raise DomainError('Managed rule file cannot be a symlink.')
        return set(files)

    def _check_ownership(self, rules):
        if 'cursor' in self.formats:
            owned = self._owned_manifest()
            for rule in rules:
                name = f'codeneuro-{slugify(rule.title)}-{hashlib.sha256(rule.id.encode()).hexdigest()[:24]}.mdc'
                path = self.root / '.cursor' / 'rules' / name
                if path.exists() and name not in owned:
                    raise Conflict('A generated rule filename collides with an unowned local file; move or review that file.')
        if 'claude' in self.formats:
            path = self.root / 'CLAUDE.md'
            if path.is_symlink():
                raise DomainError('CLAUDE.md cannot be a symlink.')
            if path.exists():
                text = path.read_text(encoding='utf-8')
                start, end = '<!-- codeneuro:start -->', '<!-- codeneuro:end -->'
                if start in text or end in text:
                    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
                        raise Conflict('CLAUDE.md has malformed managed markers; review before syncing.')
        if self.managed_file.exists():
            saved = json.loads(self.managed_file.read_text(encoding='utf-8'))
            for name, expected in saved.get('hashes', {}).items():
                # Only compare CodeNeuro-owned sections. Human prose before and
                # after the CLAUDE markers is deliberately outside the hash.
                if name == 'CLAUDE.md' and 'claude' in self.formats:
                    path = self.root / name
                    text = path.read_text(encoding='utf-8') if path.exists() else ''
                    start, end = text.find('<!-- codeneuro:start -->'), text.find('<!-- codeneuro:end -->')
                    actual = _digest(text[start:end + len('<!-- codeneuro:end -->')]) if start >= 0 and end >= start else None
                elif 'cursor' in self.formats and name.startswith('.cursor/rules/') and Path(name).parent.as_posix() == '.cursor/rules':
                    path = self.root / name
                    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
                else:
                    continue
                if actual is not None and actual != expected:
                    raise Conflict('A managed snapshot was edited locally; preserve/reconcile that edit before syncing.')

    def _remember_hashes(self):
        hashes = {}
        if 'cursor' in self.formats:
            for name in self._owned_manifest():
                path = self.root / '.cursor' / 'rules' / name
                if path.exists():
                    hashes['.cursor/rules/' + name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if 'claude' in self.formats:
            path = self.root / 'CLAUDE.md'
            if path.exists():
                text = path.read_text(encoding='utf-8')
                start, end = text.find('<!-- codeneuro:start -->'), text.find('<!-- codeneuro:end -->')
                if start >= 0 and end >= start:
                    hashes['CLAUDE.md'] = _digest(text[start:end + len('<!-- codeneuro:end -->')])
        _write(self.managed_file, {'hashes': hashes, 'formats': list(self.formats)})

    def _missing_snapshot(self):
        if not self.managed_file.exists():
            return True
        saved = json.loads(self.managed_file.read_text(encoding='utf-8'))
        for name in saved.get('hashes', {}):
            if name == 'CLAUDE.md' and 'claude' in self.formats and not (self.root / name).exists():
                return True
            if ('cursor' in self.formats and name.startswith('.cursor/rules/')
                    and Path(name).parent.as_posix() == '.cursor/rules' and not (self.root / name).exists()):
                return True
        return False

    def _export(self, rules, task):
        self._check_ownership(rules)
        paths = []
        if 'cursor' in self.formats:
            paths.extend(str(p.relative_to(self.root)) for p in RuleExporter.export_cursor_rules(rules, self.root, task))
        if 'claude' in self.formats:
            path = RuleExporter.export_claude_md(rules, self.root / 'CLAUDE.md', task)
            paths.append(str(path.relative_to(self.root)))
        self._remember_hashes()
        return paths

    def _invalidate(self):
        try:
            self._export([], None)
            self._fingerprint = None
            return None
        except Exception as exc:
            # A manual edit/permission failure must remain visible rather than
            # claiming stale generated content was removed successfully.
            return type(exc).__name__

    def _sync(self):
        attempted = _stamp()
        try:
            for _ in range(3):
                payload, rules, fingerprint = self._snapshot()
                self._check_ownership(rules)
                changed = fingerprint != self._fingerprint or self._missing_snapshot()
                if changed:
                    paths = self._export(rules, payload['task_id'])
                    latest, _, confirmed = self._snapshot()
                    if confirmed != fingerprint:
                        error = self._invalidate()
                        if error:
                            raise Conflict('Task/rules changed during export and invalidation could not finish.')
                        continue
                    self._fingerprint = fingerprint
                else:
                    paths = self._status.get('files', [])
                self._last_success, self._last_success_monotonic = _stamp(), time.monotonic()
                self._retry = self.poll_interval
                return self._publish_status(state='current', last_attempt_at=attempted, task_id=payload['task_id'],
                    binding_revision=payload['binding_revision'], rule_count=len(rules), fingerprint=fingerprint,
                    files=paths, managed_snapshots_valid=True, next_retry_seconds=self.poll_interval,
                    error=None, invalidation_error=None, changed=changed)
            raise Conflict('Task/rules keep changing while syncing; retry after the current mutation completes.')
        except Exception as exc:
            invalidation_error = self._invalidate()
            status = self._publish_status(state='stale', last_attempt_at=attempted, managed_snapshots_valid=False,
                next_retry_seconds=self._retry, changed=False, error=type(exc).__name__,
                invalidation_error=invalidation_error, rule_count=0 if not invalidation_error else self._status['rule_count'])
            self._retry = min(self.max_backoff, self._retry * 2)
            return status

    def sync_once(self):
        """One reconciled export; leaves snapshots present and reports failures."""
        with self._mutex, _lease(self.state_dir / 'sync.lock'):
            return self._sync()

    def watch(self, stop_event: threading.Event | None = None):
        """Run until stop_event/KeyboardInterrupt; Event.wait is promptly cancellable.

        Polling is explicit in status. No stream timeout is interpreted as a rule
        change or a process restart. Each retry reconciles the whole snapshot.
        """
        stop = stop_event or threading.Event()
        with self._mutex, _lease(self.state_dir / 'sync.lock'):
            self._watching = True
            try:
                while not stop.is_set():
                    result = self._sync()
                    stop.wait(result['next_retry_seconds'])
            except KeyboardInterrupt:
                stop.set()
            finally:
                invalidation_error = self._invalidate() if self.invalidate_on_stop else None
                self._watching = False
                result = self._publish_status(state='stopped', next_retry_seconds=0,
                    managed_snapshots_valid=False if self.invalidate_on_stop else self._status['managed_snapshots_valid'],
                    invalidation_error=invalidation_error,
                    rule_count=0 if self.invalidate_on_stop and not invalidation_error else self._status['rule_count'])
        return result
