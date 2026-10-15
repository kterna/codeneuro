"""V2 contract acceptance: topic CRUD, explicit levels, evidence and safe cutover.

These tests use real temporary SQLite migrations when explicitly run, never the user's DB.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import threading

from alembic import command
from alembic.config import Config
from mcp.server.mcpserver.exceptions import ToolError
from fastapi import FastAPI
import httpx
import pytest
import sqlalchemy as sa

import codeneuro
from codeneuro.adapters.http.api import create_router
from codeneuro.adapters.mcp.tools import create_mcp
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.context import ContextQuery
from codeneuro.modules.knowledge import Priority
from codeneuro.modules.tasks import Conflict, ProductError
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product

REVIEW = {'kind': 'review', 'basis': 'Human confirmed this normative project contract'}
PLAN = {'kind': 'test', 'checks': [
    {'id': 'invalidate-pointer', 'clause_indexes': [0], 'test_ids': ['VolumeRevisionIT#invalidate']},
]}


def config(filename):
    value = Config()
    value.set_main_option('script_location', str(Path(codeneuro.__file__).parent / 'migrations'))
    value.set_main_option('codeneuro_db', str(filename))
    return value


@pytest.fixture
def app(tmp_path):
    filename = tmp_path / 'v2.db'
    command.upgrade(config(filename), 'head')
    uow = SqliteUnitOfWork(str(filename))
    product = Product(uow)
    human, agent = Actor('owner', 'human'), Actor('agent')
    product.workspaces.register_project(human, 'p', 'Project')
    product.workspaces.register_project(human, 'q', 'Other project')
    task = product.workspaces.create_task(agent, 'p', 'Revise a volume')
    session = product.workspaces.start_session(agent, 'p', '/attested/worktree', task.id, debug=True)
    for key in ('git-workflow', 'volume-revision', 'frontend-layout'):
        product.topics.create_topic(human, key, key, 'Business boundary: ' + key, 'Fixture registration', project_id='p')
    yield product, uow, human, agent, task, session, filename
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
    product, _, human, agent, _, session, _ = app
    git = reviewed(product, human, 'git-workflow', patterns=('**',))
    volume = reviewed(product, human, 'volume-revision', priority=Priority.P0)
    layout = reviewed(product, human, 'frontend-layout', patterns=('frontend/**',), priority=Priority.P2)
    suggestion = reviewed(product, human, 'frontend-layout', priority=Priority.P3)
    with pytest.raises(Conflict, match='disabled'):
        product.context.get_context(agent, session.id,
            ContextQuery(priorities=(Priority.P1,), topics=('git-workflow',)))
    enable(product, human)
    git_query = ContextQuery(priorities=(Priority.P0, Priority.P1), topics=('git-workflow',))
    git_delivery = product.context.get_context(agent, session.id, git_query, 'git')
    assert {ref[0] for ref in git_delivery.rule_refs} == {git.id}
    assert product.context.get_context(agent, session.id, git_query, 'git') == git_delivery
    delivery = product.context.get_context(agent, session.id, ContextQuery(
        priorities=(Priority.P0, Priority.P1, Priority.P2), files=('frontend/layout.vue',), topics=('frontend-layout',)))
    assert {ref[0] for ref in delivery.rule_refs} == {layout.id}
    pure_business = product.context.get_context(agent, session.id, ContextQuery(
        priorities=(Priority.P0,), files=('unrelated/controller.java',), topics=('volume-revision',)))
    assert pure_business.rule_refs == ((volume.id, 1, 'full'),)
    assert pure_business.match_reasons[volume.id] == ('topic',)
    suggestions = product.context.get_context(agent, session.id, ContextQuery(
        priorities=(Priority.P3,), topics=('frontend-layout',)))
    assert {ref[0] for ref in suggestions.rule_refs} == {suggestion.id}
    files_only = product.context.get_context(agent, session.id, ContextQuery(
        priorities=(Priority.P1, Priority.P2), files=('frontend/layout.vue',)))
    assert {ref[0] for ref in files_only.rule_refs} == {git.id, layout.id}


def test_global_and_known_never_override_selected_priority_set(app):
    product, _, human, agent, _, session, _ = app
    guard = reviewed(product, human, 'volume-revision', priority=Priority.P0, is_global=True)
    ordinary = reviewed(product, human, 'git-workflow')
    enable(product, human)
    query = ContextQuery(priorities=(Priority.P0, Priority.P1), topics=('git-workflow',))
    full = product.context.get_context(agent, session.id, query)
    product.feedback.rate_rule(agent, session.id, full.id, guard.id, 0, 'Known redline')
    product.feedback.rate_rule(agent, session.id, full.id, ordinary.id, 0, 'Known convention')
    again = product.context.get_context(agent, session.id, query)
    assert (guard.id, 1, 'full') in again.rule_refs
    assert (ordinary.id, 1, 'reminder') in again.rule_refs
    only_p1 = product.context.get_context(agent, session.id,
        ContextQuery(priorities=(Priority.P1,), topics=('git-workflow',)))
    assert guard.id not in {item[0] for item in only_p1.rule_refs}


def test_topic_crud_reference_protection_tombstones_and_history(app):
    product, uow, human, agent, task, session, _ = app
    topic = product.topics.create_topic(agent, 'new-topic', 'New', 'Original boundary', 'Create explicitly', session_id=session.id)
    updated = product.topics.update_topic(agent, topic.key, 1, 'Clarify before use', description='Precise boundary', session_id=session.id)
    assert updated.version == 2
    with pytest.raises(Conflict):
        product.topics.update_topic(agent, topic.key, 1, 'Stale edit', name='Stale', session_id=session.id)
    rule = reviewed(product, human, topic.key, task_id=task.id)
    current = product.topics.get_topic(human, 'p', topic.key, True)
    assert current['definition_locked'] and current['blocking_references']['rules'] == 1
    with pytest.raises(Conflict, match='immutable'):
        product.topics.update_topic(agent, topic.key, current['version'], 'Change meaning', description='Different meaning', session_id=session.id)
    with pytest.raises(ProductError, match='Reclassify'):
        product.topics.delete_topic(agent, topic.key, current['version'], 'Try cascading', session_id=session.id)
    renamed = product.topics.update_topic(agent, topic.key, current['version'], 'Display only', name='New display', session_id=session.id)
    enable(product, human)
    query = ContextQuery(priorities=(Priority.P1,), topics=(topic.key,))
    old_delivery = product.context.get_context(agent, session.id, query, 'immutable-delivery')
    with uow.write() as tx:
        tx.knowledge.deprecate_rule(rule)
    finding = product.context.record_finding(agent, session.id, None, 'Unreviewed observation', topics=(topic.key,))
    with pytest.raises(ProductError):
        product.topics.delete_topic(agent, topic.key, renamed.version, 'Finding still references it', session_id=session.id)
    product.context.update_finding(agent, finding.id, finding.version, 'Resolved explicitly', resolve=True, session_id=session.id)
    deleted = product.topics.delete_topic(agent, topic.key, renamed.version, 'No live references remain', session_id=session.id)
    assert deleted.status == 'deleted'
    with pytest.raises(Conflict):
        product.topics.create_topic(agent, topic.key, 'Reused', 'New semantics', 'Attempt reuse', session_id=session.id)
    assert product.context.get_context(agent, session.id, query, 'immutable-delivery') == old_delivery
    with pytest.raises(ProductError, match='not active'):
        product.context.get_context(agent, session.id, query, 'new-delivery')
    with uow.read() as tx:
        assert tx.knowledge.rule_snapshot(rule.id, 1)['topics'] == [topic.key]
        assert not tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall()


def test_unknown_or_cross_project_topics_rollback_draft_and_audit(app):
    product, uow, human, agent, _, session, _ = app
    product.topics.create_topic(human, 'other-only', 'Other', 'Other project boundary', 'Registered elsewhere', project_id='q')
    with pytest.raises(ProductError, match='not active'):
        product.governance.create_task_rule(agent, session.id, 'Wrong project', ('Clause',), (), 'Reason',
            topics=('other-only',), validation_spec=REVIEW)
    with uow.read() as tx:
        assert not tx.knowledge.project_rules('p')


def test_pathless_test_rule_requires_declared_cases_for_every_check(app):
    product, _, human, agent, _, session, _ = app
    rule = product.governance.create_task_rule(agent, session.id, 'Invalidate signature result',
        ('Invalidate signed pointer after revision',), (), 'Observed invariant', priority=Priority.P0,
        topics=('volume-revision',), validation_spec=PLAN, priority_reason='Signed legal result may be reused incorrectly')['rule']
    with pytest.raises(Conflict):
        product.governance.review_task_rule(human, 'p', rule['id'], 1, True, 'Do not bypass tests')
    start = datetime.now(timezone.utc)
    def report(number, test_id):
        stamp = (start + timedelta(seconds=number)).isoformat()
        return product.governance.report_test(agent, session.id, f'run-{number}', ('host-test', test_id), (), 0,
            stamp, stamp, ({'test_id': test_id, 'status': 'passed'},))
    unrelated = report(0, 'SomeOtherTest')
    with pytest.raises(ProductError, match='declared tests'):
        product.governance.observe_rule(agent, session.id, rule['id'], 1, unrelated.id, True, 'Same Task', ('invalidate-pointer',))
    reports = [report(i, 'VolumeRevisionIT#invalidate') for i in (1, 2)]
    for item in reports:
        product.governance.observe_rule(agent, session.id, rule['id'], 1, item.id, True, 'Covered clause', ('invalidate-pointer',))
    active = product.governance.mutate_task_rule(agent, session.id, rule['id'], 1, 'activate', 'Validated')['rule']
    assert active['status'] == 'active' and active['patterns'] == ()
    changed = product.governance.mutate_task_rule(agent, session.id, rule['id'], active['version'],
        'update', 'Widen applicability', topics=('volume-revision', 'git-workflow'))['rule']
    assert changed['status'] == 'draft'
    with pytest.raises(Conflict, match='content revision'):
        product.governance.observe_rule(agent, session.id, rule['id'], changed['version'], reports[0].id,
                                        True, 'Cannot reuse old report', ('invalidate-pointer',))


def test_each_declared_check_requires_its_own_evidence(app):
    product, _, _, agent, _, session, _ = app
    plan = {'kind': 'test', 'checks': [
        {'id': 'a', 'clause_indexes': [0], 'test_ids': ['A']},
        {'id': 'b', 'clause_indexes': [1], 'test_ids': ['B']},
    ]}
    created = product.governance.create_task_rule(agent, session.id, 'Two clauses', ('First', 'Second'), (),
        'Both checks matter', topics=('volume-revision',), validation_spec=plan)['rule']
    start = datetime.now(timezone.utc)
    for number in range(2):
        stamp = (start + timedelta(seconds=number)).isoformat()
        report = product.governance.report_test(agent, session.id, f'partial-{number}', ('test-A',), (), 0,
            stamp, stamp, ({'test_id': 'A', 'status': 'passed'},))
        product.governance.observe_rule(agent, session.id, created['id'], 1, report.id, True, 'Only A', ('a',))
    with pytest.raises(Conflict, match='two distinct'):
        product.governance.mutate_task_rule(agent, session.id, created['id'], 1, 'activate', 'B lacks evidence')


def test_review_rule_and_pending_proposal_block_topic_deletion(app):
    product, _, human, agent, task, session, _ = app
    target = reviewed(product, human, 'volume-revision', priority=Priority.P0)
    candidate = product.governance.create_task_rule(agent, session.id, 'Reviewed convention', ('Use Chinese commits',), (),
        'User policy', topics=('git-workflow',), validation_spec=REVIEW)['rule']
    with pytest.raises(Conflict, match='test evidence'):
        product.governance.mutate_task_rule(agent, session.id, candidate['id'], 1, 'activate', 'No human review')
    proposal = product.knowledge.propose_contract(agent, session.id, target.id, 1, candidate['id'], 1, 'Proposed revision')
    current = product.topics.get_topic(human, 'p', 'git-workflow', True)
    assert current['blocking_references']['proposals'] == 1
    product.knowledge.review_contract(human, 'p', proposal.id, True, 'Approved normative basis')
    rule = next(r for r in product.ledger.project(human, 'p')['rules'] if r['id'] == target.id)
    assert rule['topics'] == ('git-workflow',) and rule['validation_spec'] == REVIEW


def test_stale_topic_update_and_failed_audit_are_atomic(app):
    product, uow, human, agent, _, session, filename = app
    topic = product.topics.get_topic(human, 'p', 'git-workflow')
    barrier = threading.Barrier(2)
    second = SqliteUnitOfWork(str(filename))
    def update(service, title):
        barrier.wait()
        try:
            service.topics.update_topic(agent, topic['key'], topic['version'], 'Concurrent edit', name=title, session_id=session.id)
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
        product.topics.create_topic(agent, 'must-rollback', 'Rollback', 'Boundary', 'Rollback test', session_id=session.id)
    with uow.read() as tx:
        assert tx.topics.get('p', 'must-rollback') is None


@pytest.mark.asyncio
async def test_mcp_v2_required_fields_and_catalogue(app):
    product, _, _, agent, _, session, _ = app
    server = create_mcp(product, lambda ctx: agent)
    tools = {item.name: item for item in await server.list_tools()}
    query = tools['codeneuro_get_context'].input_schema
    assert 'priorities' in query['required']
    assert 'default' not in query['properties']['priorities']
    assert not {'categories', 'min_priority'} & query['properties'].keys()
    assert {'codeneuro_create_topic', 'codeneuro_get_topic', 'codeneuro_list_topics',
            'codeneuro_update_topic', 'codeneuro_delete_topic'} <= tools.keys()
    response = await server.call_tool('codeneuro_get_context', {
        'session_id': session.id, 'priorities': ['P3'], 'files': ['src/a.py']})
    assert not response.is_error
    assert json.loads(response.content[0].text)['query']['priorities'] == ['P3']
    assert query['additionalProperties'] is False
    for extra in ({'categories': ['business']}, {'min_priority': 'P1'}):
        with pytest.raises(ToolError):
            await server.call_tool('codeneuro_get_context', {
                'session_id': session.id, 'priorities': ['P3'], 'files': ['src/a.py'], **extra})


@pytest.mark.asyncio
async def test_http_topic_crud_and_explicit_preview_levels(app):
    product, _, human, _, _, _, _ = app
    web = FastAPI()
    web.include_router(create_router(product))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web), base_url='http://test') as client:
        missing = await client.get('/api/projects/p/inspect', params={'path': 'src/a.py'})
        assert missing.status_code == 422
        preview = await client.get('/api/projects/p/inspect', params={'path': 'src/a.py', 'priorities': 'P3'})
        assert preview.status_code == 200 and preview.json()['preview']
        created = await client.post('/api/projects/p/topics', json={
            'key': 'ui-topic', 'name': 'UI', 'description': 'UI business boundary', 'reason': 'Explicit creation'})
        assert created.status_code == 200
        first = created.json()
        invalid = await client.patch('/api/projects/p/topics/ui-topic', json={
            'expected_version': first['version'], 'key': 'renamed-key', 'reason': 'Key is immutable'})
        assert invalid.status_code == 422
        updated = await client.patch('/api/projects/p/topics/ui-topic', json={
            'expected_version': first['version'], 'name': 'New display', 'reason': 'Display change'})
        assert updated.status_code == 200
        detail = await client.get('/api/projects/p/topics/ui-topic', params={'include_usage': 'true'})
        assert detail.json()['can_delete']
        deleted = await client.request('DELETE', '/api/projects/p/topics/ui-topic', json={
            'expected_version': updated.json()['version'], 'reason': 'No live usage'})
        assert deleted.status_code == 200 and deleted.json()['status'] == 'deleted'
        page = await client.get('/api/projects/p/topics')
        assert 'ui-topic' not in {item['key'] for item in page.json()['items']}
    first_page = product.topics.list_topics(human, 'p', limit=2)
    second_page = product.topics.list_topics(human, 'p', cursor=first_page['next_cursor'], limit=2)
    assert len(first_page['items']) == 2 and len(second_page['items']) == 1
    assert not {t['key'] for t in first_page['items']} & {t['key'] for t in second_page['items']}


def test_upgrade_preserves_legacy_snapshots_and_requires_classification(tmp_path):
    filename = tmp_path / 'legacy.db'
    cfg = config(filename)
    command.upgrade(cfg, '1f7a79740655')
    engine = sa.create_engine(sa.engine.URL.create('sqlite', database=str(filename)))
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO projects(id,name) VALUES ('p','Legacy')")
        connection.exec_driver_sql("INSERT INTO rules(id,project_id,title,points_json,patterns_json,priority,category,status,version) VALUES ('old','p','Old redline','[\"Keep data\"]','[\"**\"]','P0','security','active',1)")
        connection.exec_driver_sql("INSERT INTO rule_versions(rule_id,version,title,points_json,patterns_json,priority,category,status) SELECT id,version,title,points_json,patterns_json,priority,category,status FROM rules")
    engine.dispose()
    command.upgrade(cfg, 'head')
    uow = SqliteUnitOfWork(str(filename))
    try:
        product = Product(uow)
        human = Actor('owner', 'human')
        with uow.read() as tx:
            assert tx.knowledge.rule_snapshot('old', 1)['category'] == 'security'
            assert tx.knowledge.get_rule('old').topics == ()
            assert tx.topics.coverage('p')['rules'] == ['old']
            assert tx.c.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
            assert not tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall()
            assert tx.c.exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
            assert 'category' not in {c['name'] for c in sa.inspect(tx.c).get_columns('rules')}
        with pytest.raises(Conflict, match='incomplete'):
            product.topics.enable_query(human, 'p', 0, 'Not classified')
        product.topics.create_topic(human, 'data-safety', 'Data safety', 'Data loss boundaries', 'Classify legacy rules', project_id='p')
        updated = product.knowledge.classify_legacy_rule(human, 'p', 'old', 1, ('data-safety',),
            'Human re-confirmed normative data policy', patterns=(), priority_reason='Irrecoverable data loss')
        assert updated.version == 2
        enable(product, human)
        with uow.read() as tx:
            assert tx.knowledge.rule_snapshot('old', 1)['category'] == 'security'
            assert 'category' not in tx.knowledge.rule_snapshot('old', 2)
    finally:
        uow.dispose()
