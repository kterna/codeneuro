"""Session-free MCP contract, bounded resource bodies and actual immutable Deliveries."""
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from codeneuro.adapters.mcp.tools import create_mcp
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from helpers import initialize_database, configure_fixture, PLAN


@pytest.fixture
def mcp(tmp_path):
    filename = tmp_path / 'mcp.db'
    initialize_database(filename)
    uow = SqliteUnitOfWork(str(filename))
    product = Product(uow)
    human, agent = Actor('owner', 'human'), Actor('agent')
    product.workspaces.register_project(human, 'p', 'project')
    configure_fixture(product, human, ('p',))
    yield create_mcp(product, lambda ctx: agent), product, human, agent
    uow.dispose()


def unwrap(result):
    assert not result.is_error, result
    assert result.structured_content is None and len(result.content) == 1
    return json.loads(result.content[0].text)


async def scope(server, title='Business goal'):
    requirement = unwrap(await server.call_tool('codeneuro_requirement', {
        'project_id': 'p', 'action': 'create', 'changes': {'title': title, 'text': 'Overall scope'}}))
    task = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'requirement_id': requirement['id'], 'action': 'create',
        'changes': {'title': 'Independent work', 'description': 'Own scope'}}))
    return requirement, task


@pytest.mark.asyncio
async def test_catalogue_has_no_session_lifecycle_or_duplicate_output(mcp):
    server, *_ = mcp
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert len(names) == 21
    assert {'codeneuro_task', 'codeneuro_requirement', 'codeneuro_get_delivery',
            'codeneuro_open_rules'} <= names
    assert not {'codeneuro_start_session', 'codeneuro_end_session'} & names
    for tool in tools:
        assert tool.output_schema is None
        assert 'session_id' not in tool.input_schema['properties']
    context_tool = next(tool for tool in tools if tool.name == 'codeneuro_get_context')
    assert context_tool.input_schema['properties']['situation']['default'] == ''
    assert 'required' not in context_tool.input_schema['properties']['situation']
    assert unwrap(await server.call_tool('codeneuro_list_projects', {}))[0]['id'] == 'p'


@pytest.mark.asyncio
async def test_directory_exposes_metadata_and_opens_only_selected_bodies(mcp):
    server, product, human, _ = mcp
    git = product.knowledge.create_rule(human, 'p', 'Git workflow', ('GIT_BODY_ONLY',), ('src/**',),
        delivery_mode='card', applies_when='准备 commit、merge 或 push 时')
    signing = product.knowledge.create_rule(human, 'p', 'Signing boundary', ('SIGNING_BODY_ONLY',), ('src/**',),
        delivery_mode='card', applies_when='分析或修改签章调用与事务逻辑时')
    unrelated = product.knowledge.create_rule(human, 'p', 'Other files', ('OTHER_BODY_ONLY',), ('docs/**',),
        delivery_mode='card', applies_when='修改文档时')
    args = {'project_id': 'p', 'files': ['src/sign.py'], 'priorities': ['P1'],
            'situation': '分析签章逻辑', 'request_id': 'on-demand', 'max_chars': 512}
    context = unwrap(await server.call_tool('codeneuro_get_context', args))
    assert 'sections' not in context and not context['omitted_rule_ids']
    assert {tuple(ref) for ref in context['rule_refs']} == {(rule.id, rule.version, 'card') for rule in (git, signing)}
    assert not context['budget_exceeded']
    assert 'codeneuro_open_rules' in context['markdown']
    for rule in (git, signing):
        assert f'{rule.id}@{rule.version} {rule.title} — {rule.applies_when}' in context['markdown']
        assert context['markdown'].count(rule.title) == 1
        assert rule.points[0] not in json.dumps(context)
    with product.context.uow.read() as tx:
        assert not tx.context.delivery_selections(context['id'])
    with pytest.raises(ToolError, match='not offered'):
        await server.call_tool('codeneuro_open_rules', {'delivery_id': context['id'],
            'rule_ids': [unrelated.id], 'reason': 'Outside the recorded directory'})
    opening = {'delivery_id': context['id'], 'rule_ids': [signing.id], 'reason': '当前正在分析签章事务边界'}
    opened = unwrap(await server.call_tool('codeneuro_open_rules', opening))
    assert [rule['id'] for rule in opened['rules']] == [signing.id]
    assert signing.points[0] in opened['rules'][0]['markdown']
    assert git.points[0] not in json.dumps(opened)
    assert unwrap(await server.call_tool('codeneuro_open_rules', opening)) == opened
    with product.context.uow.read() as tx:
        selected = tx.context.delivery_selections(context['id'])
        assert [(item['rule_id'], item['version']) for item in selected] == [(signing.id, signing.version)]
    assert unwrap(await server.call_tool('codeneuro_get_context', args)) == context


@pytest.mark.asyncio
async def test_task_verification_then_explicit_requirement_acceptance(mcp):
    server, product, _, agent = mcp
    requirement, task = await scope(server)
    context = unwrap(await server.call_tool('codeneuro_get_context', {
        'project_id': 'p', 'task_id': task['id'], 'files': ['src/pay.py'], 'priorities': ['P1'],
        'request_id': 'actual-context'}))
    assert 'protocol_version' not in context and 'sections' not in context
    assert context['task_refs'] == [[task['id'], 1]]
    assert context['requirement_refs'][0][0] == requirement['id']
    for status in ('testing', 'completed'):
        changes = {'status': status}
        if status == 'completed':
            changes['verification_summary'] = 'Manual acceptance scenario passed'
        task = unwrap(await server.call_tool('codeneuro_task', {
            'project_id': 'p', 'action': 'update', 'id': task['id'],
            'expected_version': task['version'], 'changes': changes, 'reason': 'Explicit test progress'}))
    current = unwrap(await server.call_tool('codeneuro_requirement', {
        'project_id': 'p', 'action': 'get', 'id': requirement['id']}))
    assert current['status'] == 'accepting'
    accepted = unwrap(await server.call_tool('codeneuro_requirement', {
        'project_id': 'p', 'action': 'update', 'id': current['id'], 'expected_version': current['version'],
        'changes': {'status': 'completed', 'completion_summary': 'Overall scenarios verified'},
        'reason': 'User explicitly confirmed overall acceptance'}))
    assert accepted['status'] == 'completed'
    replay = unwrap(await server.call_tool('codeneuro_get_delivery', {'delivery_id': context['id']}))
    assert replay == product.context.get_delivery(agent, context['id'])
    assert {key: value for key, value in replay.items() if key != 'sections'} == context
    fresh = unwrap(await server.call_tool('codeneuro_get_context', {
        'project_id': 'p', 'task_id': task['id'], 'files': ['src/pay.py'], 'priorities': ['P1']}))
    assert fresh['scope']['requirement_status'] == 'completed' and fresh['scope']['read_only']


@pytest.mark.asyncio
async def test_saved_delivery_preserves_all_original_fields(mcp):
    server, product, _, _ = mcp
    saved = {'id': 'historical-delivery', 'markdown': '原始下发正文', 'rule_refs': [],
             'sections': {'original': [{'text': '保留当时已存的结构化正文'}]},
             'historical_metadata': {'unchanged': True}}
    with product.context.uow.write() as tx:
        tx.c.exec_driver_sql(
            'INSERT INTO deliveries (id,project_id,task_id,response_json,source_json,created_at) VALUES (?,?,?,?,?,?)',
            (saved['id'], 'p', None, json.dumps(saved, ensure_ascii=False), '{}', '2024-01-01T00:00:00+00:00'))
    replay = unwrap(await server.call_tool('codeneuro_get_delivery', {'delivery_id': saved['id']}))
    assert replay == saved


@pytest.mark.asyncio
async def test_bounded_list_and_get_history_include_archived_work(mcp):
    server, *_ = mcp
    requirement, _ = await scope(server)
    created = []
    for number in range(3):
        item = unwrap(await server.call_tool('codeneuro_task', {
            'project_id': 'p', 'requirement_id': requirement['id'], 'action': 'create',
            'changes': {'title': str(number) + 'x' * 220, 'description': 'd' * 250}}))
        created.append(item)
    archived = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'update', 'id': created[0]['id'], 'expected_version': 1,
        'changes': {'archived': True}, 'reason': 'Store unfinished history'}))
    assert archived['status'] == 'active' and archived['archived_at']
    page = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'list', 'requirement_id': requirement['id'], 'limit': 2}))
    following = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'list', 'requirement_id': requirement['id'], 'limit': 2,
        'cursor': page['next_cursor']}))
    items = page['items'] + following['items']
    assert len({item['id'] for item in items}) == 4
    assert any(item['archived_at'] for item in items)
    assert all(len(item['title']) <= 200 and len(item['description']) <= 200 for item in items)
    full = unwrap(await server.call_tool('codeneuro_task', {
        'project_id': 'p', 'action': 'get', 'id': archived['id'], 'history_limit': 1}))
    assert len(full['title']) == 221 and len(full['history']) == 1 and full['next_history_cursor'] == 1
    with pytest.raises(ToolError, match='cursor|Cursor'):
        await server.call_tool('codeneuro_task', {'project_id': 'p', 'action': 'list',
            'statuses': ['testing'], 'limit': 2, 'cursor': page['next_cursor']})


@pytest.mark.asyncio
@pytest.mark.parametrize('name,args', [
    ('codeneuro_task', {'project_id': 'p', 'action': 'create', 'changes': {'title': 'Missing parent'}}),
    ('codeneuro_requirement', {'project_id': 'p', 'action': 'create', 'changes': {'text': 'Missing title'}}),
    ('codeneuro_task', {'project_id': 'p', 'action': 'list', 'limit': 101}),
    ('codeneuro_get_context', {'project_id': 'p', 'priorities': ['P1'], 'files': ['src/']}),
    ('codeneuro_get_context', {'project_id': 'p', 'priorities': ['P1'], 'session_id': 'obsolete', 'files': ['a.py']}),
    ('codeneuro_get_context', {'project_id': 'p', 'priorities': ['P9'], 'files': ['a.py']}),
    ('codeneuro_get_context', {'project_id': 'p', 'priorities': ['P1'], 'task_id': 'missing', 'files': ['a.py']}),
    ('codeneuro_get_context', {'project_id': 'p', 'priorities': ['P1'], 'files': ['a.py'], 'file_path': 'b.py'}),
    ('codeneuro_requirement', {'project_id': 'p', 'action': 'create', 'changes': {'title': None, 'text': 'Bad'}}),
])
async def test_missing_scope_old_parameters_and_invalid_inputs_fail(mcp, name, args):
    server, *_ = mcp
    with pytest.raises(ToolError):
        await server.call_tool(name, args)


@pytest.mark.asyncio
async def test_topic_and_feedback_calls_need_no_session_or_debug(mcp):
    server, product, human, agent = mcp
    _, task = await scope(server)
    topic = unwrap(await server.call_tool('codeneuro_create_topic', {
        'project_id': 'p', 'key': 'payments', 'name': 'Payments', 'description': 'Payment accounting', 'reason': 'New business focus'}))
    assert topic['project_id'] == 'p'
    rule = product.knowledge.create_rule(human, 'p', 'Contract', ('Full normative clause',), ('src/**',))
    delivery = unwrap(await server.call_tool('codeneuro_get_context', {
        'project_id': 'p', 'task_id': task['id'], 'priorities': ['P1'], 'files': ['src/pay.py']}))
    unwrap(await server.call_tool('codeneuro_rate_rule', {
        'delivery_id': delivery['id'], 'rule_id': rule.id, 'score': 0, 'reason': 'Known in this conversation'}))
    candidate = unwrap(await server.call_tool('codeneuro_create_task_rule', {
        'task_id': task['id'], 'title': 'Candidate', 'content_points': ['Test this'], 'scope_patterns': [],
        'topics': ['test-contracts'], 'validation_spec': PLAN, 'reason': 'Implement requirement'}))
    assert candidate['rule']['task_id'] == task['id']
    finding = unwrap(await server.call_tool('codeneuro_record_finding', {
        'task_id': task['id'], 'topics': ['test-contracts'], 'text': 'Needs later review'}))
    resolved = unwrap(await server.call_tool('codeneuro_update_finding', {
        'task_id': task['id'], 'finding_id': finding['id'], 'expected_version': 1, 'reason': 'Reviewed', 'resolve': True}))
    assert resolved['status'] == 'resolved'
    fresh = unwrap(await server.call_tool('codeneuro_get_context', {
        'project_id': 'p', 'task_id': task['id'], 'priorities': ['P1'], 'files': ['src/pay.py']}))
    assert 'Full normative clause' in fresh['markdown']
