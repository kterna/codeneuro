"""Topic selection, explicit priorities, classification and evidence contracts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import threading

from fastapi import FastAPI
import httpx
from mcp.server.mcpserver.exceptions import ToolError
import pytest
import sqlalchemy as sa

from codeneuro.adapters.http.api import create_router
from codeneuro.adapters.mcp.tools import create_mcp
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.context import ContextQuery
from codeneuro.modules.knowledge import Priority
from codeneuro.modules.tasks import Conflict, ProductError
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from helpers import initialize_database, create_scope

REVIEW = {'kind': 'review', 'basis': 'Human confirmed this normative project contract'}
PLAN = {'kind': 'test', 'checks': [
    {'id': 'invalidate-pointer', 'clause_indexes': [0], 'test_ids': ['VolumeRevisionIT#invalidate']},
]}


@pytest.fixture
def app(tmp_path):
    filename = tmp_path / 'topics.db'
    initialize_database(filename)
    uow = SqliteUnitOfWork(str(filename))
    product = Product(uow)
    human, agent = Actor('owner', 'human'), Actor('agent')
    for project in ('p', 'q'):
        product.workspaces.register_project(human, project, project)
    parent, task = create_scope(product, agent)
    for key in ('git-workflow', 'volume-revision', 'frontend-layout'):
        product.topics.create_topic(human, key, key, 'Business boundary: ' + key, 'Fixture registration', project_id='p')
    yield product, uow, human, agent, task, parent, filename
    uow.dispose()


def enable(product, human):
    state = product.topics.list_topics(human, 'p')
    product.topics.enable_query(human, 'p', state['taxonomy_revision'], 'Reviewed classification and P0 coverage')


def reviewed(product, human, key, *, priority=Priority.P1, patterns=(), is_global=False, task_id=None):
    return product.knowledge.create_rule(human, 'p', key + ' contract', ('Must hold',), patterns,
        priority, task_id, topics=(key,), is_global=is_global,
        validation_spec=REVIEW, priority_reason='Legal effect or irreversible loss')


def test_explicit_priority_arrays_and_no_empty_project_query():
    with pytest.raises(TypeError):
        ContextQuery(files=('src/a.py',))
    for levels in ((), (Priority.P1, Priority.P1), ('P1',)):
        with pytest.raises(ProductError):
            ContextQuery(priorities=levels, files=('src/a.py',))
    with pytest.raises(ProductError):
        ContextQuery(priorities=(Priority.P0,))
    query = ContextQuery(priorities=(Priority.P3, Priority.P1), topics=('git-workflow',))
    assert query.priorities == (Priority.P1, Priority.P3)


def test_topics_are_focus_not_or_expansion_and_p0_is_not_broadcast(app):
    product, _, human, agent, *_ = app
    git = reviewed(product, human, 'git-workflow', patterns=('**',))
    volume = reviewed(product, human, 'volume-revision', priority=Priority.P0)
    layout = reviewed(product, human, 'frontend-layout', patterns=('frontend/**',), priority=Priority.P2)
    suggestion = reviewed(product, human, 'frontend-layout', priority=Priority.P3)
    with pytest.raises(Conflict, match='disabled'):
        product.context.get_context(agent, 'p', ContextQuery((Priority.P1,), topics=('git-workflow',)))
    enable(product, human)
    query = ContextQuery((Priority.P0, Priority.P1), topics=('git-workflow',))
    delivery = product.context.get_context(agent, 'p', query, 'git')
    assert {ref[0] for ref in delivery.rule_refs} == {git.id}
    assert product.context.get_context(agent, 'p', query, 'git') == delivery
    combined = product.context.get_context(agent, 'p', ContextQuery(
        (Priority.P0, Priority.P1, Priority.P2), files=('frontend/layout.vue',), topics=('frontend-layout',)))
    assert {ref[0] for ref in combined.rule_refs} == {layout.id}
    business = product.context.get_context(agent, 'p', ContextQuery(
        (Priority.P0,), files=('unrelated/controller.java',), topics=('volume-revision',)))
    assert business.rule_refs == ((volume.id, 1, 'full'),) and business.match_reasons[volume.id] == ('topic',)
    suggestions = product.context.get_context(agent, 'p', ContextQuery((Priority.P3,), topics=('frontend-layout',)))
    assert {ref[0] for ref in suggestions.rule_refs} == {suggestion.id}
    files = product.context.get_context(agent, 'p', ContextQuery((Priority.P1, Priority.P2), files=('frontend/layout.vue',)))
    assert {ref[0] for ref in files.rule_refs} == {git.id, layout.id}


def test_global_and_known_never_override_selected_priority_set(app):
    product, _, human, agent, *_ = app
    guard = reviewed(product, human, 'volume-revision', priority=Priority.P0, is_global=True)
    ordinary = reviewed(product, human, 'git-workflow')
    enable(product, human)
    query = ContextQuery((Priority.P0, Priority.P1), topics=('git-workflow',))
    full = product.context.get_context(agent, 'p', query)
    product.feedback.rate_rule(agent, full.id, guard.id, 0, 'Known redline')
    product.feedback.rate_rule(agent, full.id, ordinary.id, 0, 'Known convention')
    again = product.context.get_context(Actor('another-agent'), 'p', query)
    assert (guard.id, 1, 'full') in again.rule_refs and (ordinary.id, 1, 'full') in again.rule_refs
    only_p1 = product.context.get_context(agent, 'p', ContextQuery((Priority.P1,), topics=('git-workflow',)))
    assert guard.id not in {item[0] for item in only_p1.rule_refs}


def test_topic_crud_reference_protection_tombstones_and_history(app):
    product, uow, human, agent, task, *_ = app
    topic = product.topics.create_topic(agent, 'new-topic', 'New', 'Original boundary', 'Explicit creation', project_id='p')
    updated = product.topics.update_topic(agent, topic.key, 1, 'Clarify before use', description='Precise boundary', project_id='p')
    assert updated.version == 2
    with pytest.raises(Conflict):
        product.topics.update_topic(agent, topic.key, 1, 'Stale', name='Stale', project_id='p')
    rule = reviewed(product, human, topic.key, task_id=task.id)
    current = product.topics.get_topic(human, 'p', topic.key, True)
    assert current['definition_locked'] and current['blocking_references']['rules'] == 1
    with pytest.raises(Conflict, match='immutable'):
        product.topics.update_topic(agent, topic.key, current['version'], 'Change meaning', description='Different meaning', project_id='p')
    with pytest.raises(ProductError, match='Reclassify'):
        product.topics.delete_topic(agent, topic.key, current['version'], 'No cascade', project_id='p')
    renamed = product.topics.update_topic(agent, topic.key, current['version'], 'Display only', name='New display', project_id='p')
    enable(product, human)
    query = ContextQuery((Priority.P1,), topics=(topic.key,))
    old = product.context.get_context(agent, 'p', query, 'immutable', task_id=task.id)
    with uow.write() as tx:
        tx.knowledge.deprecate_rule(rule)
    finding = product.context.record_finding(agent, task.id, None, 'Unreviewed', topics=(topic.key,))
    with pytest.raises(ProductError):
        product.topics.delete_topic(agent, topic.key, renamed.version, 'Still referenced', project_id='p')
    product.context.update_finding(agent, finding.id, 1, 'Resolved explicitly', resolve=True, task_id=task.id)
    assert product.topics.delete_topic(agent, topic.key, renamed.version, 'Unused', project_id='p').status == 'deleted'
    with pytest.raises(Conflict):
        product.topics.create_topic(agent, topic.key, 'Reused', 'Changed semantics', 'Cannot reuse', project_id='p')
    assert product.context.get_context(agent, 'p', query, 'immutable', task_id=task.id) == old
    with pytest.raises(ProductError, match='not active'):
        product.context.get_context(agent, 'p', query, 'new', task_id=task.id)
    with uow.read() as tx:
        assert tx.knowledge.rule_snapshot(rule.id, 1)['topics'] == [topic.key]
        assert not tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall()


def test_unknown_or_cross_project_topics_rollback_draft_and_audit(app):
    product, uow, human, agent, task, *_ = app
    product.topics.create_topic(human, 'other-only', 'Other', 'Other boundary', 'Elsewhere', project_id='q')
    with pytest.raises(ProductError, match='not active'):
        product.governance.create_task_rule(agent, task.id, 'Wrong project', ('Clause',), (), 'Reason',
            topics=('other-only',), validation_spec=REVIEW)
    with uow.read() as tx:
        assert not tx.knowledge.project_rules('p')


def test_pathless_test_rule_requires_declared_cases_and_same_task_handoff(app):
    product, _, human, agent, task, *_ = app
    rule = product.governance.create_task_rule(agent, task.id, 'Invalidate signature', ('Invalidate signed pointer',), (),
        'Invariant', priority=Priority.P0, topics=('volume-revision',), validation_spec=PLAN,
        priority_reason='Signed legal result may be reused incorrectly')['rule']
    with pytest.raises(Conflict):
        product.governance.review_task_rule(human, 'p', rule['id'], 1, True, 'Cannot bypass tests')
    other = Actor('different-agent')
    start = datetime.now(timezone.utc)
    def report(number, test_id):
        stamp = (start + timedelta(seconds=number)).isoformat()
        return product.governance.report_test(other, task.id, f'run-{number}', ('host-test', test_id), (), 0,
            stamp, stamp, ({'test_id': test_id, 'status': 'passed'},))
    unrelated = report(0, 'OtherTest')
    with pytest.raises(ProductError, match='declared tests'):
        product.governance.observe_rule(other, task.id, rule['id'], 1, unrelated.id, True, 'Same Task', ('invalidate-pointer',))
    reports = [report(i, 'VolumeRevisionIT#invalidate') for i in (1, 2)]
    for item in reports:
        product.governance.observe_rule(other, task.id, rule['id'], 1, item.id, True, 'Covered', ('invalidate-pointer',))
    active = product.governance.mutate_task_rule(other, task.id, rule['id'], 1, 'activate', 'Validated')['rule']
    assert active['status'] == 'active' and active['patterns'] == ()
    changed = product.governance.mutate_task_rule(agent, task.id, rule['id'], active['version'], 'update',
        'Widen applicability', topics=('volume-revision', 'git-workflow'))['rule']
    assert changed['status'] == 'draft'
    with pytest.raises(Conflict, match='content revision'):
        product.governance.observe_rule(other, task.id, rule['id'], changed['version'], reports[0].id,
                                        True, 'Old report', ('invalidate-pointer',))


def test_each_declared_check_requires_its_own_evidence(app):
    product, _, _, agent, task, *_ = app
    plan = {'kind': 'test', 'checks': [
        {'id': 'a', 'clause_indexes': [0], 'test_ids': ['A']},
        {'id': 'b', 'clause_indexes': [1], 'test_ids': ['B']},
    ]}
    rule = product.governance.create_task_rule(agent, task.id, 'Two clauses', ('First', 'Second'), (),
        'Both matter', topics=('volume-revision',), validation_spec=plan)['rule']
    start = datetime.now(timezone.utc)
    for number in range(2):
        stamp = (start + timedelta(seconds=number)).isoformat()
        report = product.governance.report_test(agent, task.id, f'partial-{number}', ('test-A',), (), 0,
            stamp, stamp, ({'test_id': 'A', 'status': 'passed'},))
        product.governance.observe_rule(agent, task.id, rule['id'], 1, report.id, True, 'Only A', ('a',))
    with pytest.raises(Conflict, match='two distinct'):
        product.governance.mutate_task_rule(agent, task.id, rule['id'], 1, 'activate', 'B lacks evidence')


def test_review_rule_and_pending_proposal_block_topic_deletion(app):
    product, _, human, agent, task, *_ = app
    target = reviewed(product, human, 'volume-revision', priority=Priority.P0)
    candidate = product.governance.create_task_rule(agent, task.id, 'Convention', ('Use Chinese commits',), (),
        'User policy', topics=('git-workflow',), validation_spec=REVIEW)['rule']
    with pytest.raises(Conflict, match='test evidence'):
        product.governance.mutate_task_rule(agent, task.id, candidate['id'], 1, 'activate', 'No human review')
    proposal = product.knowledge.propose_contract(agent, task.id, target.id, 1, candidate['id'], 1, 'Revision')
    current = product.topics.get_topic(human, 'p', 'git-workflow', True)
    assert current['blocking_references']['proposals'] == 1
    product.knowledge.review_contract(human, 'p', proposal.id, True, 'Approved normative basis')
    rule = next(r for r in product.ledger.project(human, 'p')['rules'] if r['id'] == target.id)
    assert rule['topics'] == ('git-workflow',) and rule['validation_spec'] == REVIEW


def test_stale_topic_update_and_failed_audit_are_atomic(app):
    product, uow, human, agent, _, _, filename = app
    topic = product.topics.get_topic(human, 'p', 'git-workflow')
    barrier = threading.Barrier(2)
    second = SqliteUnitOfWork(str(filename))
    def update(service, title):
        barrier.wait()
        try:
            service.topics.update_topic(agent, topic['key'], topic['version'], 'Concurrent', name=title, project_id='p')
            return 'updated'
        except Conflict:
            return 'conflict'
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(update, service, name) for service, name in ((product, 'A'), (Product(second), 'B'))]
            assert sorted(job.result() for job in jobs) == ['conflict', 'updated']
    finally:
        second.dispose()
    with uow.write() as tx:
        tx.c.exec_driver_sql("CREATE TRIGGER refuse_topic BEFORE INSERT ON audit WHEN NEW.action='topic.created' BEGIN SELECT RAISE(ABORT,'audit failure'); END")
    with pytest.raises(Exception, match='audit failure'):
        product.topics.create_topic(agent, 'must-rollback', 'Rollback', 'Boundary', 'Rollback', project_id='p')
    with uow.read() as tx:
        assert tx.topics.get('p', 'must-rollback') is None


@pytest.mark.asyncio
async def test_mcp_required_levels_and_no_session_parameter(app):
    product, _, _, agent, task, *_ = app
    server = create_mcp(product, lambda ctx: agent)
    tools = {item.name: item for item in await server.list_tools()}
    query = tools['codeneuro_get_context'].input_schema
    assert {'project_id', 'priorities'} <= set(query['required'])
    assert 'default' not in query['properties']['priorities'] and query['additionalProperties'] is False
    assert not {'categories', 'min_priority', 'session_id'} & query['properties'].keys()
    response = await server.call_tool('codeneuro_get_context', {
        'project_id': 'p', 'task_id': task.id, 'priorities': ['P3'], 'files': ['src/a.py']})
    assert not response.is_error and json.loads(response.content[0].text)['query']['priorities'] == ['P3']
    for extra in ({'categories': ['business']}, {'min_priority': 'P1'}):
        with pytest.raises(ToolError):
            await server.call_tool('codeneuro_get_context', {'project_id': 'p', 'priorities': ['P3'], 'files': ['src/a.py'], **extra})


@pytest.mark.asyncio
async def test_http_topic_crud_and_explicit_preview_levels(app):
    product, _, human, *_ = app
    web = FastAPI()
    web.include_router(create_router(product))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web), base_url='http://test') as client:
        assert (await client.get('/api/projects/p/inspect', params={'path': 'src/a.py'})).status_code == 422
        preview = await client.get('/api/projects/p/inspect', params={'path': 'src/a.py', 'priorities': 'P3'})
        assert preview.status_code == 200 and preview.json()['preview']
        created = await client.post('/api/projects/p/topics', json={
            'key': 'ui-topic', 'name': 'UI', 'description': 'UI business boundary', 'reason': 'Explicit'})
        assert created.status_code == 200
        invalid = await client.patch('/api/projects/p/topics/ui-topic', json={'expected_version': 1, 'key': 'renamed', 'reason': 'Immutable'})
        assert invalid.status_code == 422
        updated = await client.patch('/api/projects/p/topics/ui-topic', json={'expected_version': 1, 'name': 'New display', 'reason': 'Display'})
        assert updated.status_code == 200
        assert (await client.get('/api/projects/p/topics/ui-topic', params={'include_usage': 'true'})).json()['can_delete']
        deleted = await client.request('DELETE', '/api/projects/p/topics/ui-topic', json={'expected_version': 2, 'reason': 'Unused'})
        assert deleted.status_code == 200 and deleted.json()['status'] == 'deleted'
        assert 'ui-topic' not in {item['key'] for item in (await client.get('/api/projects/p/topics')).json()['items']}
    first = product.topics.list_topics(human, 'p', limit=2)
    second = product.topics.list_topics(human, 'p', cursor=first['next_cursor'], limit=2)
    assert len(first['items']) == 2 and len(second['items']) == 1
    assert not {t['key'] for t in first['items']} & {t['key'] for t in second['items']}


def test_classification_preserves_original_snapshot(tmp_path):
    filename = tmp_path / 'classification.db'
    initialize_database(filename)
    uow = SqliteUnitOfWork(str(filename))
    with uow.write() as tx:
        tx.c.exec_driver_sql("INSERT INTO projects(id,name) VALUES ('p','Imported project')")
        tx.c.exec_driver_sql("INSERT INTO rules(id,project_id,title,points_json,patterns_json,priority,status,version) VALUES ('old','p','Old redline','[\"Keep data\"]','[\"**\"]','P0','active',1)")
        snapshot = {'rule_id': 'old', 'version': 1, 'title': 'Old redline', 'points': ['Keep data'],
                    'patterns': ['**'], 'priority': 'P0', 'category': 'security', 'status': 'active'}
        tx.c.exec_driver_sql('INSERT INTO rule_versions(rule_id,version,snapshot_json) VALUES (?,?,?)',
                            ('old', 1, json.dumps(snapshot)))
    try:
        product = Product(uow)
        human = Actor('owner', 'human')
        with uow.read() as tx:
            assert tx.knowledge.rule_snapshot('old', 1)['category'] == 'security'
            assert tx.knowledge.get_rule('old').topics == () and tx.topics.coverage('p')['rules'] == ['old']
            assert tx.c.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
            assert not tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall()
            assert tx.c.exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
            assert 'category' not in {c['name'] for c in sa.inspect(tx.c).get_columns('rules')}
        with pytest.raises(Conflict, match='incomplete'):
            product.topics.enable_query(human, 'p', 0, 'Unclassified')
        product.topics.create_topic(human, 'data-safety', 'Data safety', 'Data loss', 'Classify', project_id='p')
        updated = product.knowledge.classify_legacy_rule(human, 'p', 'old', 1, ('data-safety',),
            'Human confirmed normative policy', patterns=(), priority_reason='Irrecoverable loss')
        assert updated.version == 2
        enable(product, human)
        with uow.read() as tx:
            assert tx.knowledge.rule_snapshot('old', 1)['category'] == 'security'
            assert 'category' not in tx.knowledge.rule_snapshot('old', 2)
    finally:
        uow.dispose()
