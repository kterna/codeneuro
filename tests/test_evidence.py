"""Behavioral acceptance for receipt-backed, read-only experiment bundles."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

import codeneuro.evidence as evidence_module
from codeneuro.evidence import EvidenceError, export_bundle, sha, verify_bundle
from codeneuro.models import Priority, Project, Rule, Task
from codeneuro.remote import RemoteRegistry
from codeneuro.service import ContextService
from codeneuro.storage import Storage


def fixture(tmp_path):
    database = tmp_path / 'source.db'
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    store = Storage(str(database))
    store.create_project(Project(id='p', name='actual fixture project', root_paths=[str(workspace)]))
    store.create_task(Task(id='t', project_id='p', title='actual fixture task'))
    store.create_rule(Rule(id='r', project_id='p', task_id='t', title='protect private values',
                           content_points=['Never export PASSWORD=do-not-share.'], scope_patterns=['src/**']))
    service = ContextService(store)
    natural = service.start_session('p', str(workspace), 't', agent_client='actual fixture agent', debug=True)['id']
    diagnostic = service.start_session('p', str(workspace), 't', agent_client='probe fixture', debug=True)['id']
    first = service.resolve(session_id=natural, file_path='src/one.py')
    service.evaluate(session_id=natural, delivery_id=first.delivery_id, rule_id='r', score=4,
                     reason='Observed private value handling in actual test.')
    store.update_rule_content('r', 'protect private values', ['Never export PASSWORD=updated-secret.'],
                              ['src/**'], Priority.P1, expected_version=1)
    second = service.resolve(session_id=natural, file_path='src/two.py')
    service.evaluate(session_id=natural, delivery_id=second.delivery_id, rule_id='r', score=1,
                     reason='Not relevant to this second file.')
    probe = service.resolve(session_id=diagnostic, file_path='src/probe.py')
    service.evaluate(session_id=diagnostic, delivery_id=probe.delivery_id, rule_id='r', score=0,
                     reason='This is a diagnostic fixture, not coding.')
    store.close()
    labels = tmp_path / 'classification.json'
    labels.write_text(json.dumps({'sessions': {
        natural: {'category': 'natural', 'tool_log_sha256': 'a' * 64},
        diagnostic: {'category': 'diagnostic', 'tool_log_sha256': 'b' * 64}}}), encoding='utf-8')
    return database, labels, natural, first.delivery_id


def test_export_preserves_historical_versions_and_excludes_diagnostic(tmp_path):
    database, labels, natural, first_delivery = fixture(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    bundle = tmp_path / 'shareable'
    exported = export_bundle(database, 'p', bundle, classification_path=labels)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert exported['summary']['deliveries_total'] == 3
    assert exported['summary']['deliveries_natural'] == 2
    assert exported['summary']['feedback_rows_natural'] == 2
    assert exported['summary']['distinct_project_rule_versions_natural'] == 2
    assert exported['summary']['excluded_feedback_rows'] == 1
    assert verify_bundle(bundle)['verified']
    public = (bundle / 'evidence.json').read_text(encoding='utf-8')
    for private in ('PASSWORD=', str(tmp_path), natural, first_delivery, 'Observed private value'):
        assert private not in public
    evidence = json.loads(public)
    assert {v['version'] for v in evidence['rule_versions']} == {1, 2}
    assert all(ref['observed_content_sha256'] == ref['historical_content_sha256']
               for ref in evidence['delivery_rules'] if ref['representation'] == 'full')
    assert all('reason' not in rating for rating in evidence['ratings'])
    assert not (bundle / 'source.db').exists()


def test_unknown_is_not_natural_and_private_expansion_is_explicit(tmp_path):
    database, labels, _, _ = fixture(tmp_path)
    public = export_bundle(database, 'p', tmp_path / 'unknown')['summary']
    assert public['deliveries_natural'] == public['feedback_rows_natural'] == 0
    bundle = tmp_path / 'private'
    export_bundle(database, 'p', bundle, classification_path=labels, private=True)
    expanded = json.loads((bundle / 'evidence.json').read_text(encoding='utf-8'))
    assert any('PASSWORD=' in json.dumps(row) for row in expanded['rule_versions'])
    assert any('reason' in row for row in expanded['ratings'])
    assert verify_bundle(bundle)['privacy'] == 'private'


def test_demo_source_overrides_operator_natural_label_and_session_filter(tmp_path):
    database, labels, natural, _ = fixture(tmp_path)
    selected = export_bundle(database, 'p', tmp_path / 'selected',
                             session_id=natural, task_id='t', classification_path=labels)['summary']
    assert selected['sessions'] == 1 and selected['deliveries_natural'] == 2
    store = Storage(str(database))
    with store.transaction():
        store.conn.execute("UPDATE worktree_instances SET source='demo'")
    store.close()
    excluded = export_bundle(database, 'p', tmp_path / 'demo', classification_path=labels)['summary']
    assert excluded['deliveries_natural'] == excluded['feedback_rows_natural'] == 0


def test_verifier_rejects_tampering_even_after_manifest_hash_recomputed(tmp_path):
    database, labels, _, _ = fixture(tmp_path)
    bundle = tmp_path / 'bundle'
    export_bundle(database, 'p', bundle, classification_path=labels)
    evidence_file = bundle / 'evidence.json'
    evidence = json.loads(evidence_file.read_text(encoding='utf-8'))
    evidence['ratings'][0]['version'] = 999
    evidence_file.write_text(json.dumps(evidence), encoding='utf-8')
    with pytest.raises(EvidenceError, match='checksum mismatch'):
        verify_bundle(bundle)
    manifest_file = bundle / 'manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    manifest['files']['evidence.json'] = sha(evidence_file.read_bytes())
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(EvidenceError, match='delivered rule version'):
        verify_bundle(bundle)
    evidence['ratings'][0]['version'] = 1
    evidence['deliveries'].pop(0)
    evidence_file.write_text(json.dumps(evidence), encoding='utf-8')
    manifest['files']['evidence.json'] = sha(evidence_file.read_bytes())
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(EvidenceError, match='missing receipt|missing or mismatched delivery'):
        verify_bundle(bundle)


def test_cli_export_and_verify_without_mutating_source(tmp_path):
    database, labels, _, _ = fixture(tmp_path)
    bundle = tmp_path / 'from-cli'
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    command = [sys.executable, '-m', 'codeneuro.cli']
    exported = subprocess.run(command + ['evidence-export', '--db', str(database), '--project-id', 'p',
        '--classification', str(labels), '--out', str(bundle)], capture_output=True, text=True, env=env)
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout)['summary']['feedback_rows_natural'] == 2
    verified = subprocess.run(command + ['evidence-verify', '--bundle', str(bundle)],
                              capture_output=True, text=True, env=env)
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)['verified']


def test_shareable_bundle_hashes_untrusted_remote_repository_identity(tmp_path):
    database = tmp_path / 'remote.db'
    store = Storage(str(database))
    store.create_project(Project(id='p', name='remote fixture'))
    store.create_task(Task(id='t', project_id='p', title='scope'))
    store.create_rule(Rule(id='r', project_id='p', task_id='t', title='scope',
                           scope_patterns=['src/**'], content_points=['Keep values scoped.']))
    remote = RemoteRegistry(store)
    client = remote.enroll('fixture client', ['p'], admin_configured=True)
    secret_identity = 'https://credential:do-not-export@example.invalid/private-repo'
    session = remote.start_session(client['id'], project_id='p', workspace_path='/work/repo',
        machine_name='fixture', platform='linux', task_id='t', repo_identity=secret_identity,
        agent_client='real remote fixture', debug=True)
    remote.rpc(client['id'], 'context', {'session_id': session['id'], 'file_path': 'src/file.py'})
    store.close()
    bundle = tmp_path / 'shareable-remote'
    export_bundle(database, 'p', bundle)
    output = (bundle / 'evidence.json').read_text(encoding='utf-8')
    assert secret_identity not in output and 'do-not-export' not in output
    identity = json.loads(output)['worktrees'][0]['repo_identity_sha256']
    assert re.fullmatch('[0-9a-f]{64}', identity)
    assert verify_bundle(bundle)['verified']


def test_date_filter_applies_before_row_limit_and_to_test_records(tmp_path, monkeypatch):
    database, labels, natural, _ = fixture(tmp_path)
    store = Storage(str(database))
    service = ContextService(store)
    recent = service.resolve(session_id=natural, file_path='src/recent.py')
    recent_at = store.conn.execute('SELECT created_at FROM context_deliveries WHERE id=?',
                                   (recent.delivery_id,)).fetchone()[0]
    old_at = '2000-01-01T00:00:00'
    with store.transaction():
        store.conn.execute('''INSERT INTO governance_test_runs
            (id,project_id,task_id,session_id,request_id,request_hash,command_json,
             command_hash,exit_code,stdout,stderr,started_at,finished_at,paths_json,source,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            ('old-test', 'p', 't', natural, 'old-request', 'old-request-hash', '[]',
             'old-command-hash', 0, '', '', old_at, old_at, '[]', 'synthetic', old_at))
    store.close()
    monkeypatch.setattr(evidence_module, 'MAX_ROWS', 2)
    bundle = tmp_path / 'recent-only'
    summary = export_bundle(database, 'p', bundle, session_id=natural, since=recent_at,
                            classification_path=labels)['summary']
    assert summary['deliveries_total'] == 1
    assert summary['tests_recorded'] == 0
    assert verify_bundle(bundle)['verified']


def test_verifier_rejects_cross_project_worktree_and_task_scope(tmp_path):
    database, labels, _, _ = fixture(tmp_path)
    bundle = tmp_path / 'scoped'
    export_bundle(database, 'p', bundle, task_id='t', classification_path=labels)
    evidence_file, manifest_file = bundle / 'evidence.json', bundle / 'manifest.json'
    original = json.loads(evidence_file.read_text(encoding='utf-8'))
    def rewrite(value):
        evidence_file.write_text(json.dumps(value), encoding='utf-8')
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        manifest['files']['evidence.json'] = sha(evidence_file.read_bytes())
        manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    altered = json.loads(json.dumps(original))
    altered['worktrees'][0]['project'] = 'p2'
    rewrite(altered)
    with pytest.raises(EvidenceError, match='worktree crosses project'):
        verify_bundle(bundle)
    altered = json.loads(json.dumps(original))
    altered['tasks'].append({'id': 't_other', 'project': 'p1', 'status': 'active'})
    altered['deliveries'][0]['task'] = 't_other'
    rewrite(altered)
    with pytest.raises(EvidenceError, match='selected task scope'):
        verify_bundle(bundle)
