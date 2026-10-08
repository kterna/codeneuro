"""Portable, receipt-backed experiment evidence with explicit trust limits.

The exporter opens the live database read-only and holds one SQLite read
transaction. It publishes a new bundle atomically. SHA-256 hashes detect
accidental or uncoordinated edits; they are not an authenticity signature.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile


FORMAT_VERSION = 1
MAX_ROWS = 50000
MAX_BUNDLE_BYTES = 50_000_000
CATEGORIES = {'natural', 'diagnostic', 'synthetic', 'demo', 'legacy', 'unknown'}


class EvidenceError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def timestamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (result if result.tzinfo else result.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f'invalid timestamp: {value!r}') from exc


def _ids(values, prefix):
    return {value: f'{prefix}{index}' for index, value in enumerate(sorted(set(values) - {None, ''}), 1)}


def _rows(conn, query, args=()):
    rows = [dict(row) for row in conn.execute(query, args).fetchmany(MAX_ROWS + 1)]
    if len(rows) > MAX_ROWS:
        raise EvidenceError('selected table exceeds 50000 rows; narrow the filter')
    return rows


def _where_ids(field, values):
    if not values:
        return '1=0', ()
    return field + ' IN (' + ','.join('?' for _ in values) + ')', tuple(values)


def _rows_for_ids(conn, select, field, values, *, fixed=(), order):
    """Keep each read below older SQLite parameter limits without temp writes."""
    output = []
    values = sorted(set(values))
    for offset in range(0, len(values), 500):
        group = values[offset:offset + 500]
        clause, args = _where_ids(field, group)
        output.extend(_rows(conn, select + clause + ' ORDER BY ' + order, (*fixed, *args)))
        if len(output) > MAX_ROWS:
            raise EvidenceError('selected table exceeds 50000 rows; narrow the filter')
    return output


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _classification(path):
    if path is None:
        return {}, None
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('sessions'), dict):
        raise EvidenceError('classification must contain a sessions object')
    for session_id, value in data['sessions'].items():
        if not isinstance(session_id, str) or not isinstance(value, dict) or value.get('category') not in CATEGORIES:
            raise EvidenceError('invalid session classification')
        proof = value.get('tool_log_sha256')
        if value['category'] == 'natural' and not (isinstance(proof, str) and re.fullmatch('[0-9a-f]{64}', proof)):
            raise EvidenceError('natural classification requires a tool_log_sha256')
        provider = value.get('provider_evidence_sha256')
        if provider is not None and (not isinstance(provider, str) or not re.fullmatch('[0-9a-f]{64}', provider)):
            raise EvidenceError('provider_evidence_sha256 must be a SHA-256 digest')
    return data['sessions'], sha(raw)


def _version_content(row):
    return {'title': row['title'], 'scope_patterns': json.loads(row['scope_patterns']),
            'priority': row['priority'], 'lifecycle': row['lifecycle'],
            'content_points': json.loads(row['content_points'])}


def _response_rule_content(row):
    return {key: row[key] for key in ('title', 'scope_patterns', 'priority', 'lifecycle', 'content_points')}


def collect(db, project_id, *, task_id=None, session_id=None, since=None, until=None,
            classification_path=None, private=False):
    """Collect one bounded, consistent read snapshot without opening Storage."""
    labels, labels_hash = _classification(classification_path)
    db_path = Path(db).expanduser().resolve(strict=True)
    source = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=10)
    source.row_factory = sqlite3.Row
    try:
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        schema_version = source.execute('PRAGMA user_version').fetchone()[0]
        if source.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone() is None:
            raise EvidenceError('project does not exist')
        if task_id is not None and source.execute('SELECT 1 FROM tasks WHERE id=? AND project_id=?',
                                                  (task_id, project_id)).fetchone() is None:
            raise EvidenceError('task does not belong to project')
        if session_id is not None and source.execute('SELECT 1 FROM agent_sessions WHERE id=? AND project_id=?',
                                                     (session_id, project_id)).fetchone() is None:
            raise EvidenceError('session does not belong to project')
        sessions = _rows(source, 'SELECT * FROM agent_sessions WHERE project_id=?' +
                         (' AND id=?' if session_id else '') + ' ORDER BY id',
                         (project_id, session_id) if session_id else (project_id,))
        session_ids = [row['id'] for row in sessions]
        deliveries = _rows_for_ids(source, 'SELECT * FROM context_deliveries WHERE ',
                                   'session_id', session_ids, order='session_id,id')
        if since or until:
            lower, upper = timestamp(since), timestamp(until)
            if lower and upper and lower > upper:
                raise EvidenceError('since must precede until')
            deliveries = [d for d in deliveries if (not lower or timestamp(d['created_at']) >= lower)
                          and (not upper or timestamp(d['created_at']) <= upper)]
        response = {}
        for row in deliveries:
            try:
                response[row['id']] = json.loads(row['response_json'])
            except (ValueError, TypeError) as exc:
                raise EvidenceError('delivery response is invalid JSON: ' + row['id']) from exc
        if task_id:
            deliveries = [d for d in deliveries if response[d['id']].get('task_id') == task_id]
            keep = {d['session_id'] for d in deliveries}
            sessions = [s for s in sessions if s['id'] in keep or s['task_id'] == task_id]
        session_ids = [s['id'] for s in sessions]
        delivery_ids = [d['id'] for d in deliveries]
        refs = _rows_for_ids(source, 'SELECT * FROM delivery_rules WHERE ',
                             'delivery_id', delivery_ids, order='delivery_id,rule_id')
        ratings = _rows_for_ids(source, 'SELECT * FROM rule_evaluations WHERE project_id=? AND ',
                                'session_id', session_ids, fixed=(project_id,), order='session_id,id')
        if task_id or since or until:
            ratings = [r for r in ratings if r['delivery_id'] in delivery_ids or not r['delivery_id']]
        rule_ids = {r['rule_id'] for r in refs} | {r['rule_id'] for r in ratings}
        versions = _rows_for_ids(source, 'SELECT * FROM rule_versions WHERE ',
                                 'rule_id', rule_ids, order='rule_id,version_number')
        worktree_ids = {s['worktree_id'] for s in sessions}
        worktrees = _rows_for_ids(source, 'SELECT * FROM worktree_instances WHERE ',
                                  'id', worktree_ids, order='id')
        tests = findings = issues = preflights = []
        tables = _tables(source)
        remote_identity = {}
        if 'remote_workspaces' in tables:
            remote_identity = {r['worktree_id']: r['repo_identity'] for r in _rows_for_ids(
                source, 'SELECT worktree_id,repo_identity FROM remote_workspaces WHERE ',
                'worktree_id', worktree_ids, order='worktree_id')}
        if 'governance_test_runs' in tables:
            tests = _rows_for_ids(source, 'SELECT * FROM governance_test_runs WHERE ',
                                  'session_id', session_ids, order='session_id,id')
        if 'findings' in tables:
            findings = _rows_for_ids(source, 'SELECT * FROM findings WHERE ',
                                     'session_id', session_ids, order='session_id,id')
        if 'agent_issues' in tables:
            issues = _rows_for_ids(source, 'SELECT * FROM agent_issues WHERE ',
                                   'session_id', session_ids, order='session_id,id')
        if 'governance_preflights' in tables:
            preflights = _rows_for_ids(source, 'SELECT * FROM governance_preflights WHERE ',
                                       'session_id', session_ids, order='session_id,id')
        source.execute('COMMIT')
    finally:
        source.close()

    alias = {'project': {project_id: 'p1'}, 'task': _ids(
        [task_id] + [s['task_id'] for s in sessions] + [response[d['id']].get('task_id') for d in deliveries] +
        [r['task_id'] for r in versions], 't'),
        'session': _ids(session_ids, 's'), 'worktree': _ids(worktree_ids, 'w'),
        'delivery': _ids(delivery_ids, 'd'), 'rule': _ids(rule_ids, 'r'),
        'rating': _ids([r['id'] for r in ratings], 'f'), 'test': _ids([r['id'] for r in tests], 'x'),
        'finding': _ids([r['id'] for r in findings], 'n'), 'issue': _ids([r['id'] for r in issues], 'i'),
        'preflight': _ids([r['id'] for r in preflights], 'q')}
    a = lambda kind, value: alias[kind].get(value) if value is not None else None
    version_lookup = {(r['rule_id'], r['version_number']): r for r in versions}
    data = {'format_version': FORMAT_VERSION, 'schema_version': schema_version,
            'scope': {'project': 'p1', 'task': a('task', task_id),
                      'session': a('session', session_id), 'since': since, 'until': until},
            'classification_file_sha256': labels_hash,
            'worktrees': [{'id': a('worktree', w['id']), 'project': 'p1', 'source': w['source'],
                           'branch_sha256': sha(w['git_branch']), 'git_commit': w['git_commit'],
                           'repo_identity_sha256': remote_identity.get(w['id'])} for w in worktrees],
            'sessions': [], 'deliveries': [], 'delivery_rules': [], 'rule_versions': [],
            'ratings': [], 'tests': [], 'findings': [], 'issues': [], 'preflights': [],
            'artifacts': [], 'limitations': [
                'Session categories and coding-agent identity are operator declared; a database label does not prove external agent execution.',
                'Repository identities are client reported; inspect Git artifacts before claiming distinct completed repositories.',
                'Receipt and test rows prove recording, not that a model used a rule or that a deployed service passed.',
                'Bundle SHA-256 checksums detect edits but are not signatures or proof of database provenance.']}
    source_by_worktree = {w['id']: w['source'] for w in worktrees}
    for s in sessions:
        label = labels.get(s['id'], {})
        category = label.get('category', 'unknown')
        if category not in CATEGORIES:
            raise EvidenceError('invalid classification for ' + s['id'])
        if source_by_worktree.get(s['worktree_id']) in {'demo', 'legacy'}:
            category = source_by_worktree[s['worktree_id']]
        data['sessions'].append({'id': a('session', s['id']), 'project': 'p1',
            'worktree': a('worktree', s['worktree_id']), 'task': a('task', s['task_id']),
            'agent_client_sha256': sha(s['agent_client']), 'debug': bool(s['debug']),
            'state': s['state'], 'created_at': s['created_at'], 'last_seen_at': s['last_seen_at'],
            'category': category, 'category_source': 'source_record' if source_by_worktree.get(s['worktree_id']) in {'demo', 'legacy'} else 'operator_declared' if label else 'unknown',
            'tool_log_sha256': label.get('tool_log_sha256'),
            'provider_evidence_sha256': label.get('provider_evidence_sha256')})
    for v in versions:
        content = _version_content(v)
        record = {'rule': a('rule', v['rule_id']), 'version': v['version_number'],
                  'project': a('project', v['project_id']), 'task': a('task', v['task_id']),
                  'created_at': v['created_at'], 'content_sha256': sha(content),
                  'status': v['status'], 'priority': v['priority'], 'lifecycle': v['lifecycle']}
        if private:
            record['content'] = content
        data['rule_versions'].append(record)
    for d in deliveries:
        body = response[d['id']]
        data['deliveries'].append({'id': a('delivery', d['id']), 'session': a('session', d['session_id']),
            'project': a('project', body.get('project_id')), 'task': a('task', body.get('task_id')),
            'file_sha256': sha(d['file_path']), 'request_sha256': sha(d['request_json']),
            'response_sha256': sha(d['response_json']), 'created_at': d['created_at']})
    for ref in refs:
        body = response[ref['delivery_id']]
        observed = next((r for kind in ('long_term_rules', 'short_term_rules')
                         for r in body.get(kind, []) if r.get('id') == ref['rule_id']), None)
        version = version_lookup.get((ref['rule_id'], ref['rule_version']))
        data['delivery_rules'].append({'delivery': a('delivery', ref['delivery_id']),
            'rule': a('rule', ref['rule_id']), 'version': ref['rule_version'],
            'representation': ref['representation'],
            'observed_content_sha256': sha(_response_rule_content(observed)) if observed else None,
            'historical_content_sha256': sha(_version_content(version)) if version else None})
    for r in ratings:
        record = {'id': a('rating', r['id']), 'project': a('project', r['project_id']),
                  'session': a('session', r['session_id']), 'delivery': a('delivery', r['delivery_id']),
                  'rule': a('rule', r['rule_id']), 'version': r['rule_version'],
                  'score': r['score'], 'source': r['source'], 'created_at': r['created_at'],
                  'reason_sha256': sha(r['reason'] or '')}
        if private:
            record['reason'] = r['reason'] or ''
        data['ratings'].append(record)
    for t in tests:
        data['tests'].append({'id': a('test', t['id']), 'session': a('session', t['session_id']),
            'task': a('task', t['task_id']), 'exit_code': t['exit_code'],
            'command_hash': t['command_hash'], 'stdout_sha256': sha(t['stdout']),
            'stderr_sha256': sha(t['stderr']), 'created_at': t['created_at'],
            'source': t['source']})
    for kind, rows, target in (('finding', findings, 'findings'), ('issue', issues, 'issues')):
        for r in rows:
            data[target].append({'id': a(kind, r['id']), 'session': a('session', r['session_id']),
                'task': a('task', r.get('task_id')), 'source': r['source'],
                'status': r['status'], 'content_sha256': sha(r.get('finding_text', r.get('description', ''))),
                'created_at': r['created_at']})
    for p in preflights:
        try:
            result = json.loads(p['result_json'])
        except (TypeError, ValueError):
            result = {}
        data['preflights'].append({'id': a('preflight', p['id']), 'session': a('session', p['session_id']),
            'decision': result.get('decision'), 'model': (result.get('semantic') or {}).get('provider', {}).get('model'),
            'input_sha256': p['input_hash'], 'result_sha256': sha(p['result_json']),
            'created_at': p['created_at']})
    return data


def summarize(data):
    sessions = {s['id']: s for s in data['sessions']}
    delivery = {d['id']: d for d in data['deliveries']}
    natural_ids = {d['id'] for d in data['deliveries'] if sessions[d['session']]['category'] == 'natural'}
    eligible = [r for r in data['ratings'] if r['delivery'] in natural_ids and r['source'] == 'agent']
    pairs = {(r['project'], r['rule'], r['version']) for r in eligible}
    session_pairs = {(r['session'], r['rule'], r['version']) for r in eligible}
    identities = {w['repo_identity_sha256'] for w in data['worktrees'] if w['repo_identity_sha256']}
    return {'sessions': len(sessions), 'repository_identities_client_reported': len(identities),
            'worktrees_without_repository_identity': sum(not w['repo_identity_sha256'] for w in data['worktrees']),
            'deliveries_total': len(delivery), 'deliveries_natural': len(natural_ids),
            'feedback_rows_total': len(data['ratings']), 'feedback_rows_natural': len(eligible),
            'distinct_project_rule_versions_natural': len(pairs),
            'distinct_session_rule_versions_natural': len(session_pairs),
            'excluded_feedback_rows': len(data['ratings']) - len(eligible),
            'tests_recorded': len(data['tests']), 'preflights_recorded': len(data['preflights'])}


def _validate(data):
    if data.get('format_version') != FORMAT_VERSION:
        raise EvidenceError('unsupported evidence format')
    for kind, field in [('sessions', 'id'), ('deliveries', 'id'), ('ratings', 'id'),
                        ('worktrees', 'id'), ('tests', 'id'), ('findings', 'id'),
                        ('issues', 'id'), ('preflights', 'id')]:
        values = [row[field] for row in data[kind]]
        if len(values) != len(set(values)):
            raise EvidenceError('duplicate ' + kind + ' identifier')
    sessions = {r['id']: r for r in data['sessions']}
    worktrees = {r['id']: r for r in data['worktrees']}
    deliveries = {r['id']: r for r in data['deliveries']}
    versions = {(r['rule'], r['version']): r for r in data['rule_versions']}
    refs = {(r['delivery'], r['rule']): r for r in data['delivery_rules']}
    if len(versions) != len(data['rule_versions']) or len(refs) != len(data['delivery_rules']):
        raise EvidenceError('duplicate rule version or delivery rule reference')
    for s in sessions.values():
        if s['category'] not in CATEGORIES or s['worktree'] not in worktrees:
            raise EvidenceError('session classification or worktree is invalid: ' + s['id'])
        if s['category'] == 'natural' and not re.fullmatch('[0-9a-f]{64}', s.get('tool_log_sha256') or ''):
            raise EvidenceError('natural session lacks tool log evidence: ' + s['id'])
    for d in deliveries.values():
        s = sessions.get(d['session'])
        if not s or d['project'] != s['project']:
            raise EvidenceError('delivery has missing or cross-project session: ' + d['id'])
        if timestamp(d['created_at']) < timestamp(s['created_at']):
            raise EvidenceError('delivery predates session: ' + d['id'])
    for ref in refs.values():
        d = deliveries.get(ref['delivery'])
        v = versions.get((ref['rule'], ref['version']))
        if not d or not v:
            raise EvidenceError('delivery rule has missing receipt or historical version: ' + str(ref))
        if v['project'] != d['project'] or (v['task'] and v['task'] != d['task']):
            raise EvidenceError('delivery rule crosses project or task: ' + ref['delivery'])
        if ref['historical_content_sha256'] != v['content_sha256']:
            raise EvidenceError('delivery historical content changed: ' + ref['delivery'])
        if ref['representation'] == 'full' and ref['observed_content_sha256'] != v['content_sha256']:
            raise EvidenceError('delivered rule content differs from historical version: ' + ref['delivery'])
        if timestamp(v['created_at']) > timestamp(d['created_at']):
            raise EvidenceError('rule version postdates delivery: ' + ref['delivery'])
    seen_feedback = set()
    for r in data['ratings']:
        d = deliveries.get(r['delivery'])
        if r['source'] != 'agent' and not d:
            continue  # legacy/manual rows are visible but excluded from natural counts
        if not d or r['session'] != d['session'] or r['project'] != d['project']:
            raise EvidenceError('rating has missing or mismatched delivery/session/project: ' + r['id'])
        ref = refs.get((r['delivery'], r['rule']))
        if not ref or r['version'] != ref['version']:
            raise EvidenceError('rating does not match delivered rule version: ' + r['id'])
        key = (r['delivery'], r['rule'])
        if key in seen_feedback:
            raise EvidenceError('duplicate receipt feedback: ' + r['id'])
        seen_feedback.add(key)
        if timestamp(r['created_at']) < timestamp(d['created_at']):
            raise EvidenceError('rating predates delivery: ' + r['id'])
        if not isinstance(r['score'], int) or not 0 <= r['score'] <= 5:
            raise EvidenceError('rating score outside 0..5: ' + r['id'])
        if 'reason' in r and sha(r['reason']) != r['reason_sha256']:
            raise EvidenceError('rating reason hash mismatch: ' + r['id'])
    for v in data['rule_versions']:
        if 'content' in v and sha(v['content']) != v['content_sha256']:
            raise EvidenceError('rule historical content hash mismatch: ' + v['rule'])
    for t in data['tests']:
        if t['session'] not in sessions:
            raise EvidenceError('test references missing session: ' + t['id'])
    return summarize(data)


def _write(path, content, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'wb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def export_bundle(db, project_id, out, **filters):
    data = collect(db, project_id, **filters)
    summary = _validate(data)
    target = Path(out).expanduser().absolute()
    if target.exists():
        raise EvidenceError('bundle path already exists')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.codeneuro-evidence-', dir=target.parent))
    try:
        evidence = canonical(data) + b'\n'
        report = ('# CodeNeuro experiment evidence\n\n'
                  + '\n'.join(f'- {key}: {value}' for key, value in summary.items())
                  + '\n\n## Limits\n\n' + '\n'.join('- ' + item for item in data['limitations']) + '\n').encode('utf-8')
        if len(evidence) > MAX_BUNDLE_BYTES or len(report) > MAX_BUNDLE_BYTES:
            raise EvidenceError('evidence output exceeds 50 MB; narrow the filter')
        _write(temporary / 'evidence.json', evidence)
        _write(temporary / 'report.md', report)
        manifest = {'format_version': FORMAT_VERSION, 'kind': 'codeneuro_experiment_evidence',
                    'files': {'evidence.json': sha(evidence), 'report.md': sha(report)},
                    'summary': summary, 'privacy': 'private' if filters.get('private') else 'shareable',
                    'artifact_status': 'external_artifacts_not_bundled'}
        _write(temporary / 'manifest.json', canonical(manifest) + b'\n')
        os.replace(temporary, target)
        return {'bundle': str(target), 'summary': summary, 'manifest_sha256': sha((target / 'manifest.json').read_bytes())}
    except Exception:
        for path in temporary.iterdir():
            path.unlink()
        temporary.rmdir()
        raise


def verify_bundle(path):
    given = Path(path).expanduser()
    if given.is_symlink():
        raise EvidenceError('bundle directory must not be a symlink')
    root = given.resolve(strict=True)
    if not root.is_dir():
        raise EvidenceError('bundle must be a directory')
    manifest_path = root / 'manifest.json'
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 1_000_000:
        raise EvidenceError('manifest is symlinked or oversized')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('format_version') != FORMAT_VERSION or manifest.get('kind') != 'codeneuro_experiment_evidence':
        raise EvidenceError('unsupported manifest format')
    if set(manifest.get('files', {})) != {'evidence.json', 'report.md'}:
        raise EvidenceError('manifest file list is invalid')
    for name, expected in manifest['files'].items():
        member = root / name
        if member.is_symlink() or not member.is_file() or member.stat().st_size > MAX_BUNDLE_BYTES or sha(member.read_bytes()) != expected:
            raise EvidenceError('bundle member missing or checksum mismatch: ' + name)
    data = json.loads((root / 'evidence.json').read_text(encoding='utf-8'))
    summary = _validate(data)
    if summary != manifest.get('summary'):
        raise EvidenceError('manifest summary differs from receipt-backed counts')
    return {'verified': True, 'summary': summary, 'privacy': manifest.get('privacy'),
            'limitations': data['limitations']}
