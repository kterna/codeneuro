"""Behavioral tests for immutable graph grounding, recovery and reviewed mutations."""
import copy
import json
import threading

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from codeneuro.database import Conflict, DomainError
from codeneuro.indexing import build_manifest, graph_from_manifest, is_indexable_path, parse_file, validate_manifest
from codeneuro.intelligence import IntelligenceService, create_intelligence_router, ensure_schema
from codeneuro.llm import CompatibleProvider
from codeneuro.models import Lifecycle, Priority, Project, Rule, Task, WorktreeInstance
from codeneuro.service import ContextService
from codeneuro.storage import Storage


BACKEND = '''from fastapi import FastAPI
from .service import settle
app = FastAPI()
@app.post("/api/checkout")
def checkout(payload):
    """Finalize a customer's shopping cart."""
    return settle(payload)
'''
FRONTEND = '''import { useState } from 'react';
export interface Cart { total: number }
export const Checkout = () => {
  return fetch('/api/checkout', {method: 'POST'});
};
'''


class StubProvider:
    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback or self.analyze

    @staticmethod
    def analyze(payload):
        entity = next(e for e in payload['graph']['entities'] if e['kind'] == 'endpoint')
        return {'summary': 'Checkout contract derived from endpoint and UI edge.', 'uncertainties': [], 'candidates': [{
            'title': 'Checkout preserves idempotency', 'scope_patterns': [entity['path']], 'priority': 'P0',
            'content_points': ['Repeated requests with the same idempotency key must not create duplicate charges.'],
            'rationale': 'The checkout endpoint receives cart finalization requests from Checkout; duplicate charges are critical.',
            'evidence': [{k: entity[k] for k in ('path', 'line')} | {'entity_id': entity['id']}]}]}

    def complete(self, *, system, payload, request_id):
        self.calls.append({'system': system, 'payload': payload, 'request_id': request_id})
        return {'data': self.callback(payload), 'provider': {'model': 'test-only', 'api_style': 'stub'}, 'usage': {'input_tokens': 12}}


@pytest.fixture
def environment(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'backend').mkdir()
    (repo / 'backend' / 'api.py').write_text(BACKEND)
    (repo / 'backend' / 'service.py').write_text('def settle(payload):\n    return {"paid": True}\n')
    (repo / 'Checkout.tsx').write_text(FRONTEND)
    storage = Storage(str(tmp_path / 'state.db'))
    storage.create_project(Project(id='shop', name='Shop', root_paths=[str(repo)]))
    storage.create_task(Task(id='checkout', project_id='shop', title='Reliable checkout'))
    session = ContextService(storage).start_session('shop', str(repo), 'checkout')
    provider = StubProvider()
    service = IntelligenceService(storage, provider)
    graph = service.index_local('shop', session['worktree_id'])
    yield storage, service, provider, session, graph, repo
    service.stop_worker()
    storage.close()


def test_graph_connects_python_imports_and_frontend_http_with_real_locations(tmp_path):
    manifest = validate_manifest({'schema_version': 1, 'files': [parse_file('backend/api.py', BACKEND),
        parse_file('backend/service.py', 'def settle(payload):\n    return payload\n'), parse_file('Checkout.tsx', FRONTEND)]})
    graph = graph_from_manifest(manifest)
    endpoint = next(e for e in graph['entities'] if e['kind'] == 'endpoint')
    assert endpoint['line'] == 4 and endpoint['route'] == '/api/checkout'
    assert any(e['kind'] == 'import' and e['source'] == 'backend/api.py' and e['target'] == 'backend/service.py' and e['resolved'] for e in graph['edges'])
    assert any(e['kind'] == 'http_call' and e['target'] == endpoint['id'] and e['line'] == 4 for e in graph['edges'])
    settle = next(e for e in graph['entities'] if e['name'] == 'settle')
    assert any(e['kind'] == 'call' and e['source'] == 'backend/api.py' and e['target'] == settle['id'] for e in graph['edges'])
    assert next(e for e in graph['entities'] if e['kind'] == 'component')['name'] == 'Checkout'
    assert 'lexical' in ' '.join(graph['limitations'])


def test_windows_relative_paths_router_prefixes_and_missing_git(tmp_path, monkeypatch):
    source = 'from fastapi import APIRouter\nrouter = APIRouter(prefix="/api")\n@router.get("/users")\ndef users():\n return []\n'
    manifest = validate_manifest({'schema_version': 1, 'files': [parse_file(r'src\users.py', source)]})
    assert manifest['files'][0]['path'] == 'src/users.py'
    assert next(e for e in manifest['files'][0]['entities'] if e['kind'] == 'endpoint')['route'] == '/api/users'
    with pytest.raises(DomainError):
        parse_file(r'C:\office\repo\src\users.py', source)
    (tmp_path / 'users.py').write_text(source)
    def missing(*args, **kwargs):
        raise FileNotFoundError('git')
    monkeypatch.setattr('codeneuro.indexing.subprocess.run', missing)
    fallback = build_manifest(tmp_path)
    assert fallback['files'][0]['path'] == 'users.py' and fallback['git_commit'] is None
    assert any('Git is unavailable' in item for item in fallback['limitations'])


def test_manifest_excludes_symlink_secrets_vendor_and_reports_limits(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / '.env.py').write_text('secret = "never index"')
    (root / 'public.py').write_text('def value():\n return 1')
    (root / 'huge.py').write_text('x' * 100)
    (root / 'node_modules').mkdir()
    (root / 'node_modules' / 'vendor.js').write_text('export const Secret = 1')
    outside = tmp_path / 'outside.py'
    outside.write_text('secret = 1')
    (root / 'escape.py').symlink_to(outside)
    manifest = build_manifest(root, max_file_bytes=50)
    assert [f['path'] for f in manifest['files']] == ['public.py']
    assert any('oversized' in s for s in manifest['limitations'])


def test_secret_paths_and_git_listed_symlink_ancestors_are_not_read(tmp_path, monkeypatch):
    from types import SimpleNamespace
    for path in ['.ssh/config.md', '.aws/credentials.toml', '.config/gcloud/settings.py',
                 '.codex/auth.md', '.hermes/config.toml', 'secrets.py', 'config/credentials.toml', r'.azure\keys.py']:
        assert not is_indexable_path(path)
    assert is_indexable_path('src/auth.py') and is_indexable_path(r'src\API.PY')
    (tmp_path / 'real').mkdir()
    (tmp_path / 'real' / 'source.py').write_text('x = 1')
    (tmp_path / 'link').symlink_to(tmp_path / 'real', target_is_directory=True)
    (tmp_path / 'private.md').write_text('-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----')
    def git(args, **kwargs):
        if 'ls-files' in args:
            return SimpleNamespace(returncode=0, stdout=b'link/source.py\0private.md\0real/source.py\0')
        return SimpleNamespace(returncode=0, stdout='commit')
    monkeypatch.setattr('codeneuro.indexing.subprocess.run', git)
    manifest = build_manifest(tmp_path)
    assert [f['path'] for f in manifest['files']] == ['real/source.py']
    assert any('private-key' in item for item in manifest['limitations'])


@pytest.mark.parametrize('mutation', [
    lambda m: m['files'][0].update(path='../outside.py'),
    lambda m: m['files'][0]['entities'][0].update(line=100),
    lambda m: m['files'][0]['entities'][0].update(id='forged'),
    lambda m: m['files'].append(copy.deepcopy(m['files'][0])),
    lambda m: m['files'][0].update(sha256='bad'),
])
def test_manifest_rejects_forged_paths_locations_and_identity(mutation):
    manifest = {'schema_version': 1, 'files': [parse_file('api.py', BACKEND)]}
    mutation(manifest)
    with pytest.raises(DomainError):
        validate_manifest(manifest)


def test_index_isolation_and_snapshot_idempotency(environment):
    storage, service, _, session, graph, repo = environment
    again = service.index_local('shop', session['worktree_id'])
    assert graph['snapshot_id'] == again['snapshot_id']
    storage.create_project(Project(id='other', name='Other'))
    with pytest.raises(DomainError):
        service.ingest_manifest('other', session['worktree_id'], build_manifest(repo))
    storage.register_worktree_heartbeat(WorktreeInstance(id='remote2', project_id='shop', worktree_path='/office/repo'))
    with pytest.raises(DomainError, match='Select worktree_id'):
        service.graph('shop')
    remote = service.ingest_manifest('shop', 'remote2', {'schema_version': 1, 'files': [parse_file('remote.py', 'x=1')]})
    assert remote['trust'] == 'client_attested' and remote['entities'][0]['path'] == 'remote.py'
    assert service.graph('shop', worktree_id=session['worktree_id'])['snapshot_id'] == graph['snapshot_id']


def test_analysis_is_durable_idempotent_grounded_and_requires_review(environment):
    storage, service, provider, session, graph, _ = environment
    job = service.enqueue('analysis', 'shop', 'checkout', 'req-1', text='Support safe repeat payment attempts')
    duplicate = service.enqueue('analysis', 'shop', 'checkout', 'req-1', text='Support safe repeat payment attempts')
    assert duplicate['id'] == job['id'] and duplicate['status'] == 'queued'
    with pytest.raises(Conflict):
        service.enqueue('analysis', 'shop', 'checkout', 'req-1', text='different')
    result = service.run_job(job['id'])
    assert result['status'] == 'completed'
    assert result['snapshot_id'] == graph['snapshot_id']
    assert storage.list_rules('shop') == []
    candidate = result['candidates'][0]
    approved = service.review(candidate['id'], action='approve', expected_version=1, title='Reviewed payment contract')
    rule = storage.get_rule(approved['rule_id'])
    assert rule.title == 'Reviewed payment contract' and rule.task_id == 'checkout'
    assert rule.lifecycle == Lifecycle.SHORT_TERM and rule.priority == Priority.P0
    with pytest.raises(Conflict):
        service.review(candidate['id'], action='approve', expected_version=1)
    service.run_job(job['id'])
    assert len(provider.calls) == 1 and len(storage.list_rules('shop')) == 1


def test_provider_outside_transaction_and_failure_has_no_heuristic_candidates(environment):
    storage, service, provider, _, _, _ = environment
    def fail(payload):
        assert not storage.conn.in_transaction
        raise DomainError('Provider is unavailable.', 'provider_unavailable', 503)
    provider.callback = fail
    job = service.enqueue('analysis', 'shop', 'checkout', 'fail', text='Payment')
    failed = service.run_job(job['id'])
    assert failed['status'] == 'failed' and failed['candidates'] == []
    assert failed['error']['code'] == 'provider_unavailable' and not storage.list_rules('shop')
    provider.callback = StubProvider.analyze
    service.retry(job['id'])
    completed = service.run_job(job['id'])
    assert completed['status'] == 'completed' and completed['attempts'] == 2


def test_model_cannot_invent_evidence_or_scope(environment):
    _, service, provider, _, _, _ = environment
    def hallucinate(payload):
        output = StubProvider.analyze(payload)
        output['candidates'][0]['evidence'][0]['entity_id'] = 'invented'
        return output
    provider.callback = hallucinate
    job = service.enqueue('analysis', 'shop', 'checkout', 'hallucination', text='Payment')
    failed = service.run_job(job['id'])
    assert failed['status'] == 'failed' and failed['error']['code'] == 'provider_response_invalid'
    assert not failed['candidates']


def test_expired_job_lease_recovers_from_durable_input_without_reindex(environment):
    storage, service, provider, session, old_graph, repo = environment
    job = service.enqueue('analysis', 'shop', 'checkout', 'recover', text='Payment')
    with storage.transaction():
        storage.conn.execute("UPDATE cn_intel_jobs SET status='running',lease_token='dead-process',lease_until='2000-01-01T00:00:00',attempts=1 WHERE id=?", (job['id'],))
    (repo / 'backend' / 'api.py').write_text('def renamed():\n return 2\n')
    new_graph = service.index_local('shop', session['worktree_id'])
    assert new_graph['snapshot_id'] != old_graph['snapshot_id']
    second = Storage(storage.db_path)
    try:
        recovery = IntelligenceService(second, provider)
        results = recovery.run_pending()
        assert results[0]['status'] == 'completed' and results[0]['attempts'] == 2
        assert results[0]['snapshot_id'] == old_graph['snapshot_id']
        assert results[0]['candidates'][0]['evidence'][0]['path'] == 'backend/api.py'
    finally:
        second.close()


def test_concurrent_workers_do_not_double_complete(environment):
    storage, service, provider, _, _, _ = environment
    entered, release = threading.Event(), threading.Event()
    def slow(payload):
        entered.set()
        assert release.wait(3)
        return StubProvider.analyze(payload)
    provider.callback = slow
    job = service.enqueue('analysis', 'shop', 'checkout', 'concurrent', text='Payment')
    thread = threading.Thread(target=lambda: service.run_job(job['id']))
    thread.start()
    assert entered.wait(3)
    second_storage = Storage(storage.db_path)
    try:
        second = IntelligenceService(second_storage, provider)
        duplicate = second.run_job(job['id'])
        assert duplicate['status'] == 'running'
    finally:
        release.set()
        thread.join(3)
        second_storage.close()
    assert len(provider.calls) == 1
    assert len(service.get_job(job['id'])['candidates']) == 1


def test_distillation_merges_existing_contract_and_preserves_optimistic_lock(environment):
    storage, service, provider, _, _, _ = environment
    storage.create_rule(Rule(id='stable', project_id='shop', lifecycle=Lifecycle.LONG_TERM,
        title='Payments', scope_patterns=['backend/**'], content_points=['Preserve audit events']))
    storage.create_rule(Rule(id='temporary', project_id='shop', task_id='checkout', title='Retry safely',
        scope_patterns=['backend/**'], content_points=['Use an idempotency key']))
    def distill(payload):
        output = StubProvider.analyze(payload)
        output['candidates'][0].update(action='merge', target_rule_id='stable', target_rule_version=1,
            source_rule_ids=['temporary'], content_points=['Preserve audit events', 'Use an idempotency key'])
        return output
    provider.callback = distill
    job = service.run_job(service.enqueue('distill', 'shop', 'checkout', 'distill-1')['id'])
    assert job['status'] == 'completed'
    candidate = job['candidates'][0]
    reviewed = service.review(candidate['id'], action='approve', expected_version=1)
    assert reviewed['rule_id'] == 'stable' and storage.get_rule('stable').version == 2
    assert storage.get_rule('stable').content_points == ['Preserve audit events', 'Use an idempotency key']
    # The second immutable job was analyzed against current version 2; concurrent human edit wins.
    def distill2(payload):
        output = distill(payload)
        output['candidates'][0]['target_rule_version'] = 2
        return output
    provider.callback = distill2
    later = service.run_job(service.enqueue('distill', 'shop', 'checkout', 'distill-2')['id'])
    storage.update_rule_content('stable', 'Human edit', ['Keep me'], ['backend/**'], Priority.P1, expected_version=2)
    with pytest.raises(Conflict):
        service.review(later['candidates'][0]['id'], action='approve', expected_version=1)
    assert service.get_job(later['id'])['candidates'][0]['status'] == 'pending'
    assert storage.get_rule('stable').content_points == ['Keep me']


def test_distillation_cannot_silently_drop_source_rules(environment):
    storage, service, _, _, _, _ = environment
    storage.create_rule(Rule(id='source', project_id='shop', task_id='checkout', title='Remember me', scope_patterns=['**']))
    job = service.run_job(service.enqueue('distill', 'shop', 'checkout', 'coverage')['id'])
    assert job['status'] == 'failed'
    assert job['error']['code'] == 'provider_response_invalid'


def test_semantic_checks_every_rule_and_requires_verbatim_conflict(environment):
    storage, service, provider, _, _, _ = environment
    rule = storage.create_rule(Rule(id='p0', project_id='shop', lifecycle=Lifecycle.LONG_TERM,
        title='Retain audit', priority=Priority.P0, scope_patterns=['backend/**'], content_points=['Never delete payment audit records']))
    plan = 'Delete payment audit records after settlement.'
    def block(payload):
        assert not storage.conn.in_transaction
        return {'reasoning': 'Deleting audits directly contradicts retention.', 'limitations': [], 'assessments': [{
            'rule_id': 'p0', 'rule_version': 1, 'outcome': 'violation', 'reason': 'Deletion violates retention.',
            'plan_excerpt': plan, 'evidence': []}]}
    provider.callback = block
    verdict = service.semantic_assess('shop', files=['backend/api.py'], plan=plan, rules=[rule])
    assert verdict['decision'] == 'block' and verdict['rules_checked'] == [{'rule_id': 'p0', 'rule_version': 1}]
    def allow(payload):
        out = block(payload)
        out['assessments'][0].update(outcome='satisfied', plan_excerpt='', reason='Audit is preserved.')
        return out
    provider.callback = allow
    assert service.semantic_assess('shop', files=['backend/api.py'], plan='Keep audits and add an index', rules=[rule])['decision'] == 'allow'
    def allow_with_invented_nonviolation_excerpt(payload):
        out = allow(payload)
        out['assessments'][0].update(diff_excerpt='invented diff quote', plan_excerpt='invented plan quote')
        return out
    provider.callback = allow_with_invented_nonviolation_excerpt
    allowed = service.semantic_assess('shop', files=['backend/api.py'], plan='Keep audits and add an index', rules=[rule])
    assert allowed['decision'] == 'allow'
    assert allowed['assessments'][0]['diff_excerpt'] == allowed['assessments'][0]['plan_excerpt'] == ''
    assert any('nonverbatim' in message for message in allowed['limitations'])
    provider.callback = lambda payload: {'reasoning': 'Omitted rule', 'assessments': []}
    with pytest.raises(DomainError, match='every supplied rule'):
        service.semantic_assess('shop', files=[], plan='Keep audits', rules=[rule])
    provider.callback = block
    with pytest.raises(DomainError, match='not present'):
        service.semantic_assess('shop', files=[], plan='Keep audits', rules=[rule])


def test_semantic_diagnosis_validates_rule_clauses_and_shared_scope(environment):
    storage, service, provider, _, _, _ = environment
    for rid, clause in [('retain', 'Retain all payment audits.'), ('purge', 'Delete all payment audits after settlement.')]:
        storage.create_rule(Rule(id=rid, project_id='shop', lifecycle=Lifecycle.LONG_TERM,
            title=rid, scope_patterns=['backend/**'], priority=Priority.P0, content_points=[clause]))
    def diagnose(payload):
        assert not storage.conn.in_transaction
        return {'summary': 'Audit retention and deletion contradict each other.',
            'rules_checked': [{'rule_id': r['id'], 'rule_version': r['version']} for r in payload['rules']],
            'conflicts': [{'title': 'Audit retention conflict', 'severity': 'critical', 'reasoning': 'The same audit cannot be both retained and deleted.',
                'clauses': [{'rule_id': r['id'], 'rule_version': r['version'], 'excerpt': r['content_points'][0]} for r in payload['rules']],
                'suggested_resolution': 'Keep audit records and clarify retention policy.'}], 'limitations': []}
    provider.callback = diagnose
    result = service.diagnose('shop')
    assert result['assessment_type'] == 'model_semantic_review' and len(result['conflicts']) == 1
    assert service.list_diagnostics('shop')[0]['id'] == result['id']
    def invented(payload):
        output = diagnose(payload)
        output['conflicts'][0]['clauses'][0]['excerpt'] = 'Invented policy'
        return output
    provider.callback = invented
    with pytest.raises(DomainError, match='invented rule clause'):
        service.diagnose('shop')
    provider.callback = diagnose
    storage.update_rule_content('purge', 'Purge UI', ['Delete all payment audits after settlement.'], ['Checkout.tsx'], Priority.P0, expected_version=1)
    with pytest.raises(DomainError, match='no shared indexed file'):
        service.diagnose('shop')
    assert len(service.list_diagnostics('shop')) == 1


@pytest.mark.parametrize('style', ['chat_completions', 'responses'])
def test_compatible_provider_wire_format_and_json(style, monkeypatch):
    monkeypatch.setenv('CODENEURO_LLM_BASE_URL', 'https://provider.invalid/v1')
    monkeypatch.setenv('CODENEURO_LLM_API_KEY', 'private-test-key')
    monkeypatch.setenv('CODENEURO_LLM_MODEL', 'exact-user-model')
    monkeypatch.setenv('CODENEURO_LLM_API_STYLE', style)
    def handle(request):
        body = json.loads(request.content)
        assert body['model'] == 'exact-user-model'
        assert request.headers['Authorization'] == 'Bearer private-test-key'
        if style == 'responses':
            assert request.url.path == '/v1/responses' and body['store'] is False
            return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]})
        assert request.url.path == '/v1/chat/completions' and body['messages'][0]['role'] == 'system'
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = CompatibleProvider(client=client).complete(system='JSON only', payload={'question': 'Check'}, request_id='request')
    assert result['data'] == {'ok': True}
    assert result['provider'] == {'model': 'exact-user-model', 'api_style': style}


def test_provider_error_does_not_echo_secrets(monkeypatch):
    monkeypatch.setenv('CODENEURO_LLM_BASE_URL', 'https://provider.invalid/v1')
    monkeypatch.setenv('CODENEURO_LLM_API_KEY', 'private-test-key')
    monkeypatch.setenv('CODENEURO_LLM_MODEL', 'configured')
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(401, text='private-test-key'))) as client:
        with pytest.raises(DomainError) as exc:
            CompatibleProvider(client=client).complete(system='JSON', payload={}, request_id='r')
    assert 'private-test-key' not in str(exc.value) and exc.value.code == 'provider_unavailable'


def test_http_job_review_and_schema_does_not_change_core_version(environment):
    storage, service, _, _, _, _ = environment
    version = storage.conn.execute('PRAGMA user_version').fetchone()[0]
    ensure_schema(storage)
    assert storage.conn.execute('PRAGMA user_version').fetchone()[0] == version
    app = FastAPI()
    @app.exception_handler(DomainError)
    async def error(request, exc):
        return JSONResponse({'error': exc.code, 'detail': str(exc)}, status_code=exc.status)
    app.include_router(create_intelligence_router(storage, service=service))
    with TestClient(app) as client:
        queued = client.post('/api/projects/shop/analysis', json={'task_id': 'checkout', 'text': 'Safe retries', 'request_id': 'http'})
        assert queued.status_code == 202
        job = client.get('/api/analysis/jobs/' + queued.json()['id']).json()
        assert job['status'] == 'completed'
        candidate = job['candidates'][0]
        approved = client.post('/api/analysis/candidates/' + candidate['id'] + '/review', json={'action': 'approve', 'expected_version': 1})
        assert approved.status_code == 200 and approved.json()['rule_id']
        assert client.post('/api/analysis/candidates/' + candidate['id'] + '/review', json={'action': 'approve', 'expected_version': 1}).status_code == 409
