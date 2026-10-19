"""The same resource CRUD and governance catalogue works over both MCP transports."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from codeneuro.adapters.mcp.tools import create_mcp
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.knowledge import Priority
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from v2_helpers import configure_fixture, PLAN


@pytest.fixture
def mcp(tmp_path):
    root = Path(__file__).resolve().parents[1]
    filename = str(tmp_path / 'mcp.db')
    subprocess.run([sys.executable, '-B', '-m', 'codeneuro', 'migrate', '--db', filename],
                   cwd=root, capture_output=True, text=True, check=True)
    uow = SqliteUnitOfWork(filename)
    product = Product(uow)
    human, agent = Actor('owner', 'human'), Actor('agent')
    product.workspaces.register_project(human, 'p', 'project')
    configure_fixture(product, human, ('p',))
    yield create_mcp(product, lambda ctx: agent), product, human, agent
    uow.dispose()


def unwrap(result):
    assert not result.is_error, result
    assert result.structured_content is None
    assert len(result.content) == 1
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_standard_mcp_business_closure_and_actual_delivery(mcp):
    server, product, human, agent = mcp
    names = {tool.name for tool in await server.list_tools()}
    assert {'codeneuro_task', 'codeneuro_requirement', 'codeneuro_get_context',
            'codeneuro_promote_rule', 'codeneuro_record_finding', 'codeneuro_rate_rule', 'codeneuro_report_issue'} <= names
    assert not {'codeneuro_list_tasks', 'codeneuro_create_task', 'codeneuro_reopen_task',
                'codeneuro_list_requirements', 'codeneuro_submit_requirement',
                'codeneuro_reopen_requirement', 'codeneuro_archive_requirement'} & names
    task = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'create', 'changes': {'title': 'Refund feature'}}))
    assert task['version'] == 0 and 'revision' not in task
    session = unwrap(await server.call_tool('codeneuro_start_session', {
        'project_id': 'p', 'workspace': 'worktree-A', 'task_id': task['id'], 'debug': True}))
    demand = unwrap(await server.call_tool('codeneuro_requirement', {
        'task_id': task['id'], 'action': 'create', 'changes': {'text': 'Preserve original refund text'}, 'request_id': 'r-1'}))
    rule = product.knowledge.create_rule(human, 'p', 'Core', ('Never lose refund',), ('src/**',), task_id=task['id'])
    context = unwrap(await server.call_tool('codeneuro_get_context', {
        'session_id': session['id'], 'priorities': ['P0', 'P1', 'P2'],
        'files': ['src/refund.py'], 'request_id': 'delivery-1'}))
    assert demand['id'] in context['markdown']
    assert [rule.id, 1, 'full'] in context['rule_refs']
    rating = unwrap(await server.call_tool('codeneuro_rate_rule', {
        'session_id': session['id'], 'delivery_id': context['id'], 'rule_id': rule.id, 'score': 5}))
    assert rating['rule_version'] == 1
    promoted = unwrap(await server.call_tool('codeneuro_promote_rule', {
        'session_id': session['id'], 'rule_id': rule.id, 'expected_version': 1, 'reason': 'Cross-task requirement'}))
    assert promoted['task_id'] is None and promoted['points'] == ['Never lose refund']
    archived = unwrap(await server.call_tool('codeneuro_requirement', {
        'task_id': task['id'], 'action': 'update', 'id': demand['id'], 'expected_version': 1,
        'changes': {'status': 'archived', 'summary': 'Agent confirmed completion'}, 'reason': 'Completed'}))
    assert archived['status'] == 'archived'
    assert product.workspaces.list_tasks(agent, 'p')[0].status == 'archived'


@pytest.mark.asyncio
async def test_mcp_status_update_reopens_task_and_selected_requirement(mcp):
    server, product, human, agent = mcp
    task = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'create', 'changes': {'title': 'Continue refund'}}))
    requirements = []
    for original in ('Unfinished refund', 'Completed audit'):
        requirements.append(unwrap(await server.call_tool('codeneuro_requirement', {
            'task_id': task['id'], 'action': 'create', 'changes': {'text': original}})))
    rule = product.knowledge.create_rule(human, 'p', 'Temporary', ('Do not revive',),
                                         ('src/**',), task_id=task['id'])
    for requirement in requirements:
        unwrap(await server.call_tool('codeneuro_requirement', {
            'task_id': task['id'], 'action': 'update', 'id': requirement['id'], 'expected_version': 1,
            'changes': {'status': 'archived', 'summary': 'Initially marked complete'}, 'reason': 'Completed'}))
    with pytest.raises(ToolError, match='active/testing'):
        await server.call_tool('codeneuro_start_session', {
            'project_id': 'p', 'workspace': 'follow-up', 'task_id': task['id']})
    listed = unwrap(await server.call_tool('codeneuro_task', {'project_id': 'p', 'action': 'list'}))['items']
    assert isinstance(listed[0], dict) and listed[0]['status'] == 'archived'
    reopened = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'update', 'id': task['id'], 'expected_version': listed[0]['version'],
        'changes': {'status': 'active'}, 'reason': 'User confirms this task is unfinished'}))
    assert reopened['version'] == listed[0]['version'] + 1
    listed_requirements = unwrap(await server.call_tool('codeneuro_requirement', {'task_id': task['id'], 'action': 'list'}))
    assert {item['id'] for item in listed_requirements} == {item['id'] for item in requirements}
    assert all(item['status'] == 'archived' and item['version'] == 2 for item in listed_requirements)
    selected = next(item for item in listed_requirements if item['id'] == requirements[0]['id'])
    restored = unwrap(await server.call_tool('codeneuro_requirement', {
        'task_id': task['id'], 'action': 'update', 'id': selected['id'], 'expected_version': selected['version'],
        'changes': {'status': 'active'}, 'reason': 'User requests completion of refund'}))
    assert restored['text'] == selected['text']
    assert restored['version'] == 3 and restored['status'] == 'active' and restored['summary'] is None
    with pytest.raises(ToolError, match='conflict'):
        await server.call_tool('codeneuro_requirement', {
            'task_id': task['id'], 'action': 'update', 'id': selected['id'], 'expected_version': 2,
            'changes': {'status': 'active'}, 'reason': 'Stale retry'})
    bound = unwrap(await server.call_tool('codeneuro_start_session', {
        'project_id': 'p', 'workspace': 'follow-up', 'task_id': task['id']}))
    delivery = unwrap(await server.call_tool('codeneuro_get_context', {
        'session_id': bound['id'], 'priorities': ['P0', 'P1'], 'files': ['src/refund.py']}))
    assert delivery['requirement_refs'] == [[selected['id'], 3]]
    assert rule.id not in delivery['markdown']
    assert len(product.workspaces.list_tasks(agent, 'p')) == 1


@pytest.mark.asyncio
async def test_mcp_crud_revisions_soft_deletion_and_schema(mcp):
    server, _, _, _ = mcp
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert all(tool.output_schema is None for tool in tools.values())
    assert {'statuses', 'cursor', 'limit'} <= tools['codeneuro_task'].input_schema['properties'].keys()
    common = {'action', 'id', 'expected_version', 'changes', 'reason'}
    for name in ('codeneuro_task', 'codeneuro_requirement'):
        assert common <= tools[name].input_schema['properties'].keys()
        assert tools[name].input_schema['properties']['action']['enum'] == ['create', 'list', 'get', 'update', 'delete']
        assert 'actor_id' not in tools[name].input_schema['properties']
    assert not {'reopen_task', 'expected_task_revision', 'reopen_reason'} & tools['codeneuro_start_session'].input_schema['properties'].keys()
    with pytest.raises(ToolError):
        await server.call_tool('codeneuro_start_session', {'project_id': 'p', 'workspace': 'x', 'reopen_task': True})
    with pytest.raises(ToolError):
        await server.call_tool('codeneuro_task', {'project_id': 'p', 'action': 'create',
                                               'changes': {'title': 'Bad', 'unknown': True}})
    with pytest.raises(ToolError, match='not_found'):
        await server.call_tool('codeneuro_task', {'project_id': 'q', 'action': 'list'})
    task = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'create', 'changes': {'title': 'Editable'}}))
    task = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'update', 'id': task['id'], 'expected_version': task['version'],
        'changes': {'title': 'Renamed', 'description': 'More detail'}, 'reason': 'Clarify'}))
    assert task['title'] == 'Renamed'
    req = unwrap(await server.call_tool('codeneuro_requirement', {
        'task_id': task['id'], 'action': 'create', 'changes': {'text': 'Original'}, 'request_id': 'original'}))
    req = unwrap(await server.call_tool('codeneuro_requirement', {
        'task_id': task['id'], 'action': 'update', 'id': req['id'], 'expected_version': 1,
        'changes': {'text': 'Revised'}, 'reason': 'Clarify scope'}))
    assert req['text'] == 'Revised' and req['version'] == 2
    retry = unwrap(await server.call_tool('codeneuro_requirement', {
        'task_id': task['id'], 'action': 'create', 'changes': {'text': 'Original'}, 'request_id': 'original'}))
    assert retry['id'] == req['id']
    deleted = unwrap(await server.call_tool('codeneuro_requirement', {
        'task_id': task['id'], 'action': 'delete', 'id': req['id'], 'expected_version': 2, 'reason': 'Withdrawn'}))
    assert deleted['status'] == 'deleted'
    assert unwrap(await server.call_tool('codeneuro_requirement', {'task_id': task['id'], 'action': 'list'})) == []
    detail = unwrap(await server.call_tool('codeneuro_requirement', {'task_id': task['id'], 'action': 'get', 'id': req['id']}))
    assert [v['text'] for v in detail['history']] == ['Original', 'Revised', 'Revised']
    current = unwrap(await server.call_tool('codeneuro_task', {'project_id': 'p', 'action': 'get', 'id': task['id']}))
    assert current['status'] == 'active'
    unwrap(await server.call_tool('codeneuro_task', {'project_id': 'p', 'action': 'delete',
        'id': task['id'], 'expected_version': current['version'], 'reason': 'Withdrawn'}))
    assert unwrap(await server.call_tool('codeneuro_task', {'project_id': 'p', 'action': 'list'})) == {
        'items': [], 'next_cursor': None}
    assert unwrap(await server.call_tool('codeneuro_task', {'project_id': 'p', 'action': 'get', 'id': task['id']}))['status'] == 'deleted'


@pytest.mark.asyncio
async def test_agent_governance_tools_create_draft_without_executing_tests(mcp):
    server, _, _, _ = mcp
    task = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'create', 'changes': {'title': 'Evidence task'}}))
    session = unwrap(await server.call_tool('codeneuro_start_session',
        {'project_id': 'p', 'workspace': 'worktree-evidence', 'task_id': task['id']}))
    created = unwrap(await server.call_tool('codeneuro_create_task_rule', {
        'session_id': session['id'], 'title': 'Task observation',
        'content_points': ['Protect API'], 'scope_patterns': ['src/**'],
        'reason': 'Agent noticed an API constraint', 'topics': ['test-contracts'], 'validation_spec': PLAN}))
    assert created['rule']['status'] == 'draft' and created['governance']['stage'] == 'observing'
    context = unwrap(await server.call_tool('codeneuro_get_context',
        {'session_id': session['id'], 'priorities': ['P0', 'P1', 'P2'], 'file_path': 'src/api.py'}))
    assert created['rule']['id'] not in context['markdown']


@pytest.mark.asyncio
async def test_finding_mcp_reminds_other_task_session_and_appears_in_ledger(mcp):
    server, product, _, agent = mcp
    task = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'create', 'changes': {'title': 'Fix refunds'}}))
    original = unwrap(await server.call_tool('codeneuro_start_session',
        {'project_id': 'p', 'workspace': 'first', 'task_id': task['id']}))
    finding = unwrap(await server.call_tool('codeneuro_record_finding', {
        'session_id': original['id'], 'target_path': 'src/refund/**',
        'text': 'Retry must be idempotent', 'topics': ['test-contracts']}))
    another = unwrap(await server.call_tool('codeneuro_start_session',
        {'project_id': 'p', 'workspace': 'second', 'task_id': task['id']}))
    delivery = unwrap(await server.call_tool('codeneuro_get_context', {
        'session_id': another['id'], 'priorities': ['P0', 'P1', 'P2'],
        'file_path': 'src/refund/pay.py', 'intent': 'debugging'}))
    assert [finding['id'], 1] in delivery['finding_refs']
    assert 'sections' not in delivery
    assert 'Unreviewed Finding' in delivery['markdown'] and finding['text'] in delivery['markdown']
    assert finding['id'] in {item['id'] for item in product.ledger.project(agent, 'p')['findings']}


@pytest.mark.asyncio
async def test_task_pages_bound_large_history_and_preserve_full_detail(mcp):
    server, product, human, agent = mcp
    tasks = []
    for index in range(123):
        task = product.workspaces.create_task(agent, 'p', f'{index:03d} ' + '任务标题' * 100,
                                             '任务背景和业务描述' * 1000)
        if index < 121:
            task = product.workspaces.manage_task(agent, 'p', 'update', task.id, task.revision,
                                                  {'status': 'archived'}, 'Historical task')
        elif index == 121:
            task = product.workspaces.manage_task(agent, 'p', 'update', task.id, task.revision,
                                                  {'status': 'testing'}, 'Awaiting verification')
        tasks.append(task)
    deleted = tasks.pop(0)
    product.workspaces.manage_task(agent, 'p', 'delete', deleted.id, deleted.revision, reason='Withdrawn')
    product.workspaces.register_project(human, 'q', 'Other project')
    product.workspaces.create_task(agent, 'q', 'Outside project')

    args = {'project_id': 'p', 'action': 'list'}
    seen = []
    pages = 0
    while True:
        result = await server.call_tool('codeneuro_task', args)
        page = unwrap(result)
        assert len(result.content[0].text.encode('utf-8')) < 50 * 1024
        assert 1 <= len(page['items']) <= 20
        assert all(item['truncated'] and len(item['title']) == len(item['description']) == 200
                   for item in page['items'])
        seen.extend(item['id'] for item in page['items'])
        pages += 1
        if page['next_cursor'] is None:
            break
        assert page['next_cursor'] == page['items'][-1]['id']
        args['cursor'] = page['next_cursor']
    assert pages == 7
    assert seen == sorted(task.id for task in tasks)

    cursor = None
    selected = []
    for _ in range(2):
        page = unwrap(await server.call_tool('codeneuro_task', {
            'project_id': 'p', 'action': 'list', 'statuses': ['active', 'testing'], 'limit': 1, 'cursor': cursor}))
        selected.extend(page['items'])
        cursor = page['next_cursor']
    assert cursor is None and {item['status'] for item in selected} == {'active', 'testing'}
    assert {item['id'] for item in selected} == {task.id for task in tasks[-2:]}
    archived = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'list', 'statuses': ['archived'], 'limit': 100}))
    assert len(archived['items']) == 100 and archived['next_cursor']
    assert all(item['status'] == 'archived' for item in archived['items'])
    detail = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'get', 'id': tasks[-1].id}))
    assert detail['title'] == tasks[-1].title and detail['description'] == tasks[-1].description
    assert detail['version'] == tasks[-1].revision
    empty = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'list', 'statuses': ['draft']}))
    assert empty == {'items': [], 'next_cursor': None}


@pytest.mark.asyncio
@pytest.mark.parametrize('options', [
    {'limit': 0}, {'limit': 101}, {'cursor': ''}, {'cursor': 'x' * 129},
    {'statuses': []}, {'statuses': ['active', 'active']}, {'statuses': ['deleted']},
    {'statuses': ['unknown']},
    {'action': 'create', 'changes': {'title': 'Wrong action'}, 'limit': 20},
])
async def test_task_list_rejects_invalid_or_misplaced_paging_options(mcp, options):
    server, _, _, _ = mcp
    with pytest.raises(ToolError):
        await server.call_tool('codeneuro_task', {'project_id': 'p', 'action': 'list', **options})


@pytest.mark.asyncio
async def test_context_output_contains_body_once_and_preserves_delivery_snapshot(mcp):
    server, product, human, agent = mcp
    task = product.workspaces.create_task(agent, 'p', 'Compact context')
    session = product.workspaces.start_session(agent, 'p', 'compact-worktree', task.id)
    rule = product.knowledge.create_rule(human, 'p', 'Refund contract',
        ('Unique rule clause for compact output',), ('src/**',), priority=Priority.P0, task_id=task.id)
    requirement = product.requirements.manage_requirement(agent, task.id, 'create',
        changes={'text': 'Unique requirement for compact output'})
    finding = product.context.record_finding(agent, session.id, 'src/**',
                                             'Unique finding for compact output')
    args = {'session_id': session.id, 'priorities': ['P0', 'P1', 'P2'],
            'files': ['src/pay.py'], 'request_id': 'compact-context'}
    result = await server.call_tool('codeneuro_get_context', args)
    delivery = unwrap(result)
    assert 'sections' not in delivery
    for text in (rule.points[0], requirement.text, finding.text):
        assert result.content[0].text.count(text) == 1
    assert [rule.id, 1, 'full'] in delivery['rule_refs']
    assert [requirement.id, 1] in delivery['requirement_refs']
    assert [finding.id, 1] in delivery['finding_refs']
    replay = await server.call_tool('codeneuro_get_context', args)
    assert unwrap(replay) == delivery
    with product.workspaces.uow.read() as tx:
        _, snapshot = tx.context.find_delivery(session.id, 'compact-context')
    assert snapshot.markdown == delivery['markdown']
    assert snapshot.sections['must_obey_contracts']
    assert snapshot.sections['task_actionable_checklist']
    assert snapshot.sections['module_gotchas'][0]['content'].endswith(finding.text + '\n')


@pytest.mark.asyncio
async def test_exact_same_catalogue_for_two_transports(mcp):
    server, product, _, agent = mcp
    remote = create_mcp(product, lambda ctx: agent, name='CodeNeuro HTTP')
    assert {tool.name: tool.input_schema for tool in await server.list_tools()} == {
        tool.name: tool.input_schema for tool in await remote.list_tools()}
