"""Requirement/Task acceptance and session-free context integration."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Barrier

import pytest

from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork, initialize_database
from codeneuro.modules.context import ContextQuery
from codeneuro.modules.knowledge import Priority
from codeneuro.modules.tasks import Conflict, ProductError
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product


@pytest.fixture
def app(tmp_path):
    filename = str(tmp_path / 'hierarchy.db')
    initialize_database(filename)
    uow = SqliteUnitOfWork(filename)
    product = Product(uow)
    human, agent = Actor('human', 'human'), Actor('agent')
    product.workspaces.register_project(human, 'p', 'Archive')
    product.workspaces.register_project(human, 'q', 'Other')
    yield product, uow, human, agent
    uow.dispose()


def parent(product, agent, **changes):
    return product.requirements.manage_requirement(agent, 'p', 'create',
        changes={'title': '档号要素维护', 'text': '整体目标', **changes})


def get_parent(product, agent, identity):
    return product.requirements.manage_requirement(agent, 'p', 'get', identity)


def task(product, agent, requirement, title='全宗号'):
    return product.workspaces.create_task(agent, 'p', requirement.id, title, '本任务范围', acceptance_criteria='验证本任务')


def change_task(product, agent, item, **changes):
    return product.workspaces.manage_task(agent, 'p', 'update', item.id, item.version, changes, '明确操作')


def complete(product, agent, item):
    item = change_task(product, agent, item, status='testing')
    return change_task(product, agent, item, status='completed', verification_summary='人工验证通过')


def test_three_independent_tasks_require_explicit_overall_acceptance(app):
    p, uow, human, agent = app
    requirement = parent(p, agent)
    tasks = [task(p, agent, requirement, title) for title in ('全宗号', '项目代码', '类目类号')]
    first = complete(p, agent, tasks[0])
    assert get_parent(p, agent, requirement.id)['status'] == 'active'
    assert p.workspaces.manage_task(agent, 'p', 'get', tasks[1].id)['status'] == 'active'
    complete(p, agent, tasks[1])
    complete(p, agent, tasks[2])
    current = get_parent(p, agent, requirement.id)
    assert current['status'] == 'accepting'
    assert current['progress'] == {'total': 3, 'completed': 3}
    with pytest.raises(ProductError, match='completion_summary'):
        p.requirements.manage_requirement(agent, 'p', 'update', requirement.id, current['version'],
                                         {'status': 'completed'}, '用户确认')
    accepted = p.requirements.manage_requirement(agent, 'p', 'update', requirement.id, current['version'],
        {'status': 'completed', 'completion_summary': '三个要素整体联调通过'}, '用户明确确认整体验收通过')
    assert accepted.status == 'completed'
    with pytest.raises(Conflict, match='Reopen'):
        change_task(p, agent, first, status='active')
    reopened = p.requirements.manage_requirement(agent, 'p', 'update', requirement.id, accepted.version,
                                                {'status': 'active'}, '用户要求继续')
    assert reopened.completion_summary is None
    changed = change_task(p, agent, first, status='active')
    assert changed.verification_summary is None
    assert p.workspaces.manage_task(agent, 'p', 'get', changed.id)['history'][-2]['verification_summary'] == '人工验证通过'
    assert get_parent(p, agent, requirement.id)['history'][-3]['completion_summary'] == '三个要素整体联调通过'


def test_no_completion_by_deletion_or_archive_or_empty_children(app):
    p, _, _, agent = app
    requirement = parent(p, agent)
    with pytest.raises(Conflict):
        p.requirements.manage_requirement(agent, 'p', 'update', requirement.id, requirement.version,
                                         {'status': 'accepting'}, '空需求')
    item = task(p, agent, requirement)
    with pytest.raises(Conflict, match='verification'):
        change_task(p, agent, item, status='completed', verification_summary='只写完代码')
    archived = change_task(p, agent, item, archived=True)
    assert archived.status == 'active'
    with pytest.raises(Conflict, match='archived'):
        change_task(p, agent, archived, status='testing')
    restored = change_task(p, agent, archived, archived=False)
    current = get_parent(p, agent, requirement.id)
    with pytest.raises(Conflict, match='Tasks'):
        p.requirements.manage_requirement(agent, 'p', 'delete', requirement.id, current['version'], reason='还有任务')
    p.workspaces.manage_task(agent, 'p', 'delete', restored.id, restored.version, reason='缩减范围')
    current = get_parent(p, agent, requirement.id)
    assert current['status'] == 'active' and current['progress']['total'] == 0


def test_scope_versions_and_creation_replay(app):
    p, _, _, agent = app
    requirement = parent(p, agent)
    with pytest.raises(ProductError):
        p.workspaces.create_task(agent, 'q', requirement.id, 'wrong project')
    first = p.workspaces.create_task(agent, 'p', requirement.id, 'Idempotent', request_id='create-1')
    change_task(p, agent, first, title='Changed later')
    assert p.workspaces.create_task(agent, 'p', requirement.id, 'Idempotent', request_id='create-1') == first
    with pytest.raises(Conflict):
        p.workspaces.create_task(agent, 'p', requirement.id, 'Different', request_id='create-1')
    with pytest.raises(Conflict):
        change_task(p, agent, first, title='Stale overwrite')


def test_decline_acceptance_and_scope_change_do_not_complete_again(app):
    p, _, _, agent = app
    requirement = parent(p, agent)
    child = complete(p, agent, task(p, agent, requirement))
    current = get_parent(p, agent, requirement.id)
    declined = p.requirements.manage_requirement(agent, 'p', 'update', requirement.id, current['version'],
                                                {'status': 'active'}, '整体联调尚未通过')
    assert get_parent(p, agent, requirement.id)['status'] == 'active'
    with pytest.raises(Conflict):
        change_task(p, agent, child, description='改变已验证范围')
    child = change_task(p, agent, child, status='active', description='修复联调问题')
    complete(p, agent, child)
    current = get_parent(p, agent, requirement.id)
    assert current['status'] == 'accepting' and current['version'] > declined.version
    p.requirements.manage_requirement(agent, 'p', 'update', requirement.id, current['version'],
                                      {'text': '修改整体目标'}, '重新确认需求')
    assert get_parent(p, agent, requirement.id)['status'] == 'active'


def test_context_is_task_scoped_without_session_and_known_does_not_hide(app):
    p, _, human, agent = app
    requirement = parent(p, agent)
    first, other = task(p, agent, requirement), task(p, agent, requirement, 'Sibling secret')
    p.topics.create_topic(agent, 'archive', '档案', '档号业务', '明确登记', project_id='p')
    rule = p.knowledge.create_rule(human, 'p', 'Shared contract', ('Must remain complete',), ('src/**',),
        topics=('archive',), validation_spec={'kind': 'review', 'basis': '人工规范'})
    query = ContextQuery((Priority.P1,), files=('src/a.py',))
    delivery = p.context.get_context(agent, 'p', query, 'read-1', task_id=first.id)
    assert delivery.task_refs == ((first.id, first.version),)
    assert delivery.requirement_refs[0][0] == requirement.id
    assert 'Sibling secret' not in delivery.markdown and 'Topics: ' not in delivery.markdown
    p.feedback.rate_rule(agent, delivery.id, rule.id, 0)
    second = p.context.get_context(Actor('another-agent'), 'p', query, task_id=first.id)
    assert 'Must remain complete' in second.markdown
    assert p.context.get_context(agent, 'p', query, 'read-1', task_id=first.id) == delivery
    with pytest.raises(Conflict):
        p.context.get_context(agent, 'p', query, 'read-1', task_id=other.id)
    with pytest.raises(ProductError):
        p.context.get_context(agent, 'q', query, task_id=first.id)
    assert p.context.get_delivery(agent, delivery.id)['markdown'] == delivery.markdown
    assert not p.context.get_context(agent, 'p', query).task_refs


def test_overall_acceptance_racing_reopen_is_atomic(app):
    p, _, _, agent = app
    requirement = parent(p, agent)
    child = complete(p, agent, task(p, agent, requirement))
    current = get_parent(p, agent, requirement.id)
    barrier = Barrier(2)

    def accept():
        barrier.wait()
        try:
            return p.requirements.manage_requirement(agent, 'p', 'update', requirement.id, current['version'],
                {'status': 'completed', 'completion_summary': '用户确认'}, '用户明确确认通过')
        except Conflict:
            return None

    def reopen():
        barrier.wait()
        try:
            return change_task(p, agent, child, status='active')
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(accept), pool.submit(reopen)
        results = [a.result(), b.result()]
    assert sum(result is not None for result in results) == 1
    parent_now = get_parent(p, agent, requirement.id)
    child_now = p.workspaces.manage_task(agent, 'p', 'get', child.id)
    assert not (parent_now['status'] == 'completed' and child_now['status'] != 'completed')


def test_summary_pagination_and_history_are_bounded(app):
    p, _, _, agent = app
    requirement = parent(p, agent)
    for number in range(4):
        task(p, agent, requirement, str(number) + 'x' * 250)
    page = p.workspaces.manage_task(agent, 'p', 'list', requirement_id=requirement.id, limit=2)
    assert len(page['items']) == 2 and all(row['truncated'] for row in page['items'])
    next_page = p.workspaces.manage_task(agent, 'p', 'list', requirement_id=requirement.id,
                                        cursor=page['next_cursor'], limit=2)
    assert len({row['id'] for row in page['items'] + next_page['items']}) == 4
    detail = p.requirements.manage_requirement(agent, 'p', 'get', requirement.id, history_limit=2)
    assert len(detail['history']) == 2 and detail['next_history_cursor'] == 2
    assert detail['progress']['total'] == 4
