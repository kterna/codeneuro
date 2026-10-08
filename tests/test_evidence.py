"""Behavioral acceptance for receipt-backed, read-only experiment bundles."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from codeneuro.evidence import EvidenceError, export_bundle, sha, verify_bundle
from codeneuro.models import Priority, Project, Rule, Task
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
