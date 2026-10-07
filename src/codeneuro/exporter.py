"""Owned, atomic static snapshots. Human rules outside our manifest are preserved."""
import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from .database import DomainError
from .models import Lifecycle, Priority, RuleStatus


def slugify(text):
    return re.sub(r'[^\w-]+', '-', text.lower()).strip('-')[:32] or 'rule'


def atomic_text(path, text):
    fd, temporary = tempfile.mkstemp(prefix='.codeneuro-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def export_lock(root):
    lock = root / '.codeneuro-export.lock'
    if lock.is_symlink():
        raise DomainError('Export lock may not be a symlink.')
    with lock.open('a') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield


def eligible(rules, task):
    return sorted([r for r in rules if r.status == RuleStatus.ACTIVE and
        (r.lifecycle == Lifecycle.LONG_TERM or (task and r.task_id == task))], key=lambda r: (r.priority.rank, r.id))


class RuleExporter:
    @staticmethod
    def rule_to_mdc(rule):
        return '\n'.join(['---', 'description: ' + json.dumps(rule.title, ensure_ascii=False),
            'globs: ' + json.dumps(', '.join(rule.scope_patterns), ensure_ascii=False),
            'alwaysApply: ' + ('true' if '**' in rule.scope_patterns and rule.priority == Priority.P0 else 'false'),
            '---', '', f'# [{rule.priority.value}] {rule.title}',
            f'<!-- CodeNeuro {rule.id} v{rule.version} -->', '', *['- '+p for p in rule.content_points], ''])

    @classmethod
    def export_cursor_rules(cls, rules, out_dir, active_task_id=None):
        root = Path(out_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        directory = root / '.cursor' / 'rules'
        if not directory.resolve().is_relative_to(root):
            raise DomainError('Export directory escapes the workspace through a symlink.')
        directory.mkdir(parents=True, exist_ok=True)
        manifest = directory / '.codeneuro-manifest.json'
        if manifest.is_symlink():
            raise DomainError('Export manifest may not be a symlink.')
        with export_lock(root):
            previous = json.loads(manifest.read_text()) if manifest.exists() else {'files': []}
            paths = []
            for rule in eligible(rules, active_task_id):
                identity = hashlib.sha256(rule.id.encode()).hexdigest()[:24]
                dest = directory / f'codeneuro-{slugify(rule.title)}-{identity}.mdc'
                if dest.is_symlink():
                    raise DomainError('Refusing to replace a symlinked rule file.')
                atomic_text(dest, cls.rule_to_mdc(rule))
                paths.append(dest)
            names = [p.name for p in paths]
            for name in previous['files']:
                if Path(name).name != name or not name.startswith('codeneuro-') or not name.endswith('.mdc'):
                    raise DomainError('Invalid managed export manifest.')
                if name not in names:
                    old = directory / name
                    if old.is_symlink():
                        raise DomainError('Refusing to remove a symlinked rule file.')
                    old.unlink(missing_ok=True)
            atomic_text(manifest, json.dumps({'task_id': active_task_id, 'files': names}, ensure_ascii=False, indent=2))
            return paths

    @classmethod
    def export_claude_md(cls, rules, out_file, active_task_id=None):
        path = Path(out_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise DomainError('Refusing to overwrite symlinked instructions.')
        start, end = '<!-- codeneuro:start -->', '<!-- codeneuro:end -->'
        with export_lock(path.parent):
            previous = path.read_text() if path.exists() else ''
            lines = [start, '# CodeNeuro scoped rules', '> Generated snapshot; regenerate after rule/task changes.']
            for rule in eligible(rules, active_task_id):
                lines.extend([f'\n## [{rule.priority.value}] {rule.title}',
                              'Scopes: ' + ', '.join(rule.scope_patterns),
                              *['- '+p for p in rule.content_points]])
            lines.append(end)
            block = '\n'.join(lines)
            if start in previous or end in previous:
                if previous.count(start) != 1 or previous.count(end) != 1 or previous.index(start) > previous.index(end):
                    raise DomainError('Instruction file contains malformed managed markers.')
                a, b = previous.index(start), previous.index(end)+len(end)
                content = previous[:a] + block + previous[b:]
            else:
                content = previous.rstrip() + ('\n\n' if previous.strip() else '') + block + '\n'
            atomic_text(path, content)
        return path
