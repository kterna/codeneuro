"""Explicit project Rule retirement, immutable history and scoped replay."""
from dataclasses import replace
import json
from pathlib import Path
import runpy

import httpx
from fastapi import FastAPI
import pytest

from codeneuro.adapters.http.api import create_router
from codeneuro.modules.knowledge import Priority, Rule
from codeneuro.modules.tasks import Conflict, ProductError
from helpers import file_query, propose_review
from test_product_core import app, update


def retire(product, human, rule, *, request_id='retirement', **overrides):
    arguments = dict(confirmed=True, request_id=request_id)
    arguments.update(overrides)
    return product.knowledge.retire_project_rule(human, rule.project_id, rule.id, rule.version,
                                                'User confirmed the replacement coverage', **arguments)


def test_retirement_preserves_history_feedback_and_other_p0_rules(app):
    p, uow, human, agent, task, *_ = app
    noise = p.knowledge.create_rule(human, 'p', 'Git workflow', ('Only while committing',), ('src/**',), Priority.P0)
    needed = p.knowledge.create_rule(human, 'p', 'External signing', ('Keep calls outside transactions',), ('src/**',), Priority.P0)
    query = file_query(('src/sign.py',), intent='debugging')
    previous = p.context.get_context(agent, 'p', query, 'before-retirement', task_id=task.id)
    p.feedback.rate_rule(agent, previous.id, noise.id, 1, 'Only explaining fields, no Git operation')
    assert noise.id in {r[0] for r in p.context.get_context(agent, 'p', query).rule_refs}
    with uow.read() as tx:
        old_body = tx.c.exec_driver_sql('SELECT response_json FROM deliveries WHERE id=?', (previous.id,)).scalar()
        old_snapshot = tx.knowledge.rule_snapshot(noise.id, 1)
        revision = tx.workspaces.project_revision('p')
    result = retire(p, human, noise)
    assert result == {'id': noise.id, 'project_id': 'p', 'version': 2, 'status': 'deprecated'}
    assert retire(p, human, noise) == result
    fresh = p.context.get_context(agent, 'p', query, task_id=task.id)
    assert fresh.rule_refs == ((needed.id, 1, 'full'),)
    assert p.context.get_context(agent, 'p', query, 'before-retirement', task_id=task.id) == previous
    assert p.context.get_delivery(agent, previous.id) == json.loads(old_body)
    with uow.read() as tx:
        changed = tx.knowledge.get_rule(noise.id)
        assert changed == replace(noise, status='deprecated', version=2)
        assert tx.knowledge.rule_snapshot(noise.id, 1) == old_snapshot
        assert tx.knowledge.rule_snapshot(noise.id, 2)['status'] == 'deprecated'
        assert tx.workspaces.project_revision('p') == revision + 1
        assert tx.c.exec_driver_sql('SELECT response_json FROM deliveries WHERE id=?', (previous.id,)).scalar() == old_body
        assert tx.c.exec_driver_sql('SELECT score FROM feedback WHERE rule_id=?', (noise.id,)).scalar() == 1
        audit = tx.c.exec_driver_sql("SELECT details_json FROM audit WHERE action='rule.retired' AND entity_id=?", (noise.id,)).fetchall()
        assert len(audit) == 1 and json.loads(audit[0][0])['from_version'] == 1
        assert tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []
    with pytest.raises(Conflict):
        p.knowledge.retire_project_rule(human, 'p', noise.id, 1, 'Different reason', confirmed=True, request_id='retirement')
    with pytest.raises(Conflict): retire(p, human, noise, request_id='another-request')
    with pytest.raises(Conflict): retire(p, human, changed, request_id=None)


@pytest.mark.parametrize('confirmed', [False, None, 'true', 1])
def test_retirement_requires_real_boolean_confirmation(app, confirmed):
    p, uow, human, _, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Rule', ('Keep',), ('src/**',))
    with pytest.raises(ProductError, match='confirmation'):
        retire(p, human, rule, confirmed=confirmed)
    with uow.read() as tx:
        assert tx.knowledge.get_rule(rule.id) == rule


def test_agent_cannot_retire_project_rule_even_with_confirmation(app):
    p, uow, human, agent, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Rule', ('Keep',), ('src/**',))
    with pytest.raises(ProductError) as error:
        retire(p, agent, rule)
    assert error.value.code == 'forbidden'
    with uow.read() as tx:
        assert tx.knowledge.get_rule(rule.id) == rule


def test_retirement_rejects_wrong_project_task_and_stale_version(app):
    p, uow, human, _, task, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Project', ('Keep',), ('src/**',))
    local = p.knowledge.create_rule(human, 'p', 'Task', ('Keep task evidence',), ('src/**',), task_id=task.id)
    for project, target in [('q', rule.id), ('p', local.id), ('p', 'missing')]:
        with pytest.raises(ProductError) as error:
            p.knowledge.retire_project_rule(human, project, target, 1, 'Wrong scope', confirmed=True)
        assert error.value.code == 'not_found'
    with uow.write() as tx:
        changed = replace(rule, title='Changed before confirmation', version=2)
        tx.knowledge.update_rule(changed)
    with pytest.raises(Conflict): retire(p, human, rule)
    with uow.read() as tx:
        assert tx.knowledge.get_rule(rule.id) == changed
        assert tx.knowledge.get_rule(local.id) == local


@pytest.mark.parametrize('version,reason,request_id', [(0, 'Reason', None), (True, 'Reason', None),
    (1, '   ', None), (1, 'Reason', ''), (1, 'Reason', 'r' * 129)])
def test_invalid_retirement_arguments_do_not_mutate_rules(app, version, reason, request_id):
    p, uow, human, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Rule', ('Keep',), ('src/**',))
    with pytest.raises(ProductError):
        p.knowledge.retire_project_rule(human, 'p', rule.id, version, reason, confirmed=True, request_id=request_id)
    with uow.read() as tx:
        assert tx.knowledge.get_rule(rule.id) == rule


def test_retirement_rolls_back_rule_snapshot_revision_audit_and_receipt(app):
    p, uow, human, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Rule', ('Keep',), ('src/**',))
    tables = ('rules', 'rule_versions', 'audit', 'request_receipts')
    with uow.write() as tx:
        counts = {t: tx.c.exec_driver_sql(f'SELECT COUNT(*) FROM {t}').scalar() for t in tables}
        revision = tx.workspaces.project_revision('p')
        tx.c.exec_driver_sql("CREATE TRIGGER fail_retirement BEFORE INSERT ON audit WHEN NEW.action='rule.retired' BEGIN SELECT RAISE(ABORT,'injected retirement failure'); END")
    with pytest.raises(Exception, match='injected retirement failure'):
        retire(p, human, rule)
    with uow.write() as tx:
        assert tx.knowledge.get_rule(rule.id) == rule
        assert tx.workspaces.project_revision('p') == revision
        assert all(tx.c.exec_driver_sql(f'SELECT COUNT(*) FROM {t}').scalar() == n for t, n in counts.items())
        tx.c.exec_driver_sql('DROP TRIGGER fail_retirement')
    assert retire(p, human, rule)['status'] == 'deprecated'


def test_legacy_rule_can_be_retired_without_rewriting_its_old_scope(app):
    p, uow, human, agent, *_ = app
    legacy = Rule('legacy', 'p', None, 'Unclassified old rule', ('Original content',),
                  ('D:/old/workspace/**',), Priority.P0, (), 1, 'active')
    with uow.write() as tx:
        tx.knowledge.create_rule(legacy)
    retire(p, human, legacy)
    assert not p.context.get_context(agent, 'p', file_query(('src/main.py',))).rule_refs
    with uow.read() as tx:
        assert tx.knowledge.get_rule(legacy.id) == replace(legacy, version=2, status='deprecated')
        assert tx.knowledge.rule_snapshot(legacy.id, 1)['patterns'] == ['D:/old/workspace/**']


def test_pending_proposal_and_task_restore_cannot_reactivate_retired_contract(app):
    p, uow, human, agent, task, parent, _ = app
    source = p.knowledge.create_rule(human, 'p', 'Candidate', ('Reviewed',), ('src/**',), task_id=task.id)
    contract = p.knowledge.promote_rule(agent, task.id, source.id, 1, 'Reusable')
    pending = propose_review(p, agent, task.id, contract.id, 'Revision', ('Reviewed revision',), ('src/**',), Priority.P1, 'Propose')
    retire(p, human, contract)
    with pytest.raises(Conflict, match='changed since'):
        p.knowledge.review_contract(human, 'p', pending.id, True, 'Old pending proposal')
    assert p.knowledge.promote_rule(agent, task.id, source.id, 1, 'Reusable').status == 'deprecated'
    archived = update(p, agent, task, archived=True)
    restored = update(p, agent, archived, archived=False)
    for archived_state in (True, False):
        current = p.requirements.manage_requirement(agent, 'p', 'get', parent.id)
        p.requirements.manage_requirement(agent, 'p', 'update', parent.id, current['version'],
                                          {'archived': archived_state}, 'Archive/restore is not activation')
    assert contract.id not in {r[0] for r in p.context.get_context(agent, 'p', file_query(('src/a.py',)), task_id=restored.id).rule_refs}
    with uow.read() as tx:
        assert tx.knowledge.get_rule(contract.id).status == 'deprecated'
        assert tx.knowledge.get_proposal(pending.id).status == 'pending'


def test_context_rechecks_project_revision_when_rule_retires_during_assembly(app, monkeypatch):
    import codeneuro.workflows.context as context_module
    p, _, human, agent, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Rule', ('Keep until retired',), ('src/**',))
    original = context_module.assemble
    calls = []

    def assemble(*args, **kwargs):
        result = original(*args, **kwargs)
        if not calls:
            retire(p, human, rule)
        calls.append(result)
        return result

    monkeypatch.setattr(context_module, 'assemble', assemble)
    result = p.context.get_context(agent, 'p', file_query(('src/a.py',)))
    assert len(calls) == 2 and calls[0].rule_refs and not result.rule_refs


@pytest.mark.asyncio
async def test_http_retirement_confirmation_scope_replay_and_immutable_delivery(app):
    p, _, human, agent, task, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Rule', ('Keep history',), ('src/**',))
    delivery = p.context.get_context(agent, 'p', file_query(('src/a.py',)), task_id=task.id)
    web = FastAPI()
    web.include_router(create_router(p))
    path = f'/api/projects/p/rules/{rule.id}/retire'
    body = {'expected_version': 1, 'reason': 'User explicitly confirmed', 'confirmed': True, 'request_id': 'web-retirement'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web), base_url='http://test') as client:
        stored = (await client.get(f'/api/projects/p/deliveries/{delivery.id}')).json()
        for bad in ({k: v for k, v in body.items() if k != 'confirmed'}, {**body, 'confirmed': 'true'},
                    {**body, 'confirmed': 1}, {**body, 'expected_version': True},
                    {**body, 'expected_version': '1'}, {**body, 'session_id': 'obsolete'}):
            assert (await client.post(path, json=bad)).status_code == 422
        assert (await client.post(path, json={**body, 'confirmed': False})).status_code == 403
        assert (await client.post(path, json={**body, 'reason': '  '})).status_code == 400
        assert (await client.post(path.replace('/p/', '/q/'), json=body)).status_code == 404
        retired = await client.post(path, json=body)
        assert retired.status_code == 200 and retired.json()['status'] == 'deprecated'
        assert (await client.post(path, json=body)).json() == retired.json()
        assert (await client.post(path, json={**body, 'reason': 'Changed'})).status_code == 409
        assert (await client.post(path, json={**body, 'request_id': 'another'})).status_code == 409
        assert (await client.get(f'/api/projects/p/deliveries/{delivery.id}')).json() == stored
        preview = await client.get('/api/projects/p/inspect', params={'path': 'src/a.py', 'priorities': 'P1'})
        assert preview.status_code == 200 and rule.id not in json.dumps(preview.json())


@pytest.mark.asyncio
async def test_mcp_reads_retired_rules_historically_but_cannot_retire_them(app):
    from mcp.server.mcpserver.exceptions import ToolError
    from codeneuro.adapters.mcp.tools import create_mcp
    p, _, human, agent, task, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Rule', ('Preserve actual Delivery',), ('src/**',))
    server = create_mcp(p)
    assert 'codeneuro_retire_project_rule' not in {tool.name for tool in await server.list_tools()}
    with pytest.raises(ToolError):
        await server.call_tool('codeneuro_mutate_task_rule', {'task_id': task.id, 'rule_id': rule.id,
            'expected_version': 1, 'action': 'revoke', 'reason': 'Cannot use a Task to retire a project Rule'})
    delivery = p.context.get_context(agent, 'p', file_query(('src/a.py',)))
    retire(p, human, rule)
    fresh = await server.call_tool('codeneuro_get_context', {'project_id': 'p', 'priorities': ['P1'], 'files': ['src/a.py']})
    assert not fresh.is_error and json.loads(fresh.content[0].text)['rule_refs'] == []
    historical = await server.call_tool('codeneuro_get_delivery', {'delivery_id': delivery.id})
    assert not historical.is_error and historical.structured_content is None and len(historical.content) == 1
    assert json.loads(historical.content[0].text) == p.context.get_delivery(agent, delivery.id)


def test_copy_verifier_never_retires_source_rules(app):
    p, uow, human, agent, task, _, filename = app
    rule = p.knowledge.create_rule(human, 'p', 'Workflow', ('Use for Git',), ('src/**',))
    guard = p.knowledge.create_rule(human, 'p', 'Signing', ('Keep external calls outside transactions',), ('src/**',), Priority.P0)
    delivery = p.context.get_context(agent, 'p', file_query(('src/sign.py',)), task_id=task.id)
    verifier = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/verify_rule_retirement_copy.py'))['verify']
    result = verifier(Path(filename), 'p', [rule.id], [delivery.id])
    assert result['result'] == 'passed' and result['source_read_only'] and result['temporary_environment_removed']
    assert result['scenarios'][0]['retained_rule_ids'] == [guard.id]
    with uow.read() as tx:
        assert tx.knowledge.get_rule(rule.id) == rule
        assert tx.knowledge.rule_snapshot(rule.id, 2) is None
    assert (rule.id, 1, 'full') in p.context.get_context(agent, 'p', file_query(('src/sign.py',))).rule_refs
