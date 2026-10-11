"""The same MCP catalogue works over stdio and authenticated HTTP contexts."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from codeneuro.adapters.mcp.tools import create_mcp
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product


@pytest.fixture
def mcp(tmp_path):
    root = Path(__file__).resolve().parents[1]
    filename = str(tmp_path / 'mcp.db')
    subprocess.run([sys.executable, '-B', '-m', 'codeneuro',
                    'migrate', '--db', filename],
                   cwd=root, capture_output=True, text=True, check=True)
    uow = SqliteUnitOfWork(filename)
    product = Product(uow)
    human = Actor('owner', frozenset({'p'}), 'human')
    agent = Actor('agent', frozenset({'p'}))
    product.workspaces.register_project(human, 'p', 'project')
    server = create_mcp(product, lambda ctx: agent)
    yield server, product, human, agent
    uow.dispose()


def unwrap(result):
    assert not result.is_error, result
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_standard_mcp_business_closure_and_actual_delivery(mcp):
    server, product, human, agent = mcp
    names = {tool.name for tool in await server.list_tools()}
    assert {'codeneuro_list_tasks', 'codeneuro_submit_requirement', 'codeneuro_get_context',
            'codeneuro_promote_rule', 'codeneuro_archive_requirement', 'codeneuro_record_finding',
            'codeneuro_rate_rule', 'codeneuro_report_issue'} <= names
    assert not {'codeneuro_edit_file', 'codeneuro_run_tests'} & names
    task = unwrap(await server.call_tool('codeneuro_create_task', {'project_id': 'p', 'title': 'Refund feature'}))
    session = unwrap(await server.call_tool('codeneuro_start_session', {
        'project_id': 'p', 'workspace': 'worktree-A', 'task_id': task['id'], 'debug': True}))
    assert session['worktree_id'].startswith('wt_')
    demand = unwrap(await server.call_tool('codeneuro_submit_requirement', {
        'session_id': session['id'], 'text': 'Preserve original refund text', 'request_id': 'r-1'}))
    rule = product.knowledge.create_rule(human, 'p', 'Core', ('Never lose refund',), ('src/**',), task_id=task['id'])
    context = unwrap(await server.call_tool('codeneuro_get_context', {
        'session_id': session['id'], 'files': ['src/refund.py'], 'request_id': 'delivery-1'}))
    assert demand['id'] in context['markdown']
    assert [rule.id, 1, 'full'] in context['rule_refs']
    rating = unwrap(await server.call_tool('codeneuro_rate_rule', {
        'session_id': session['id'], 'delivery_id': context['id'], 'rule_id': rule.id, 'score': 5}))
    assert rating['rule_version'] == 1
    promoted = unwrap(await server.call_tool('codeneuro_promote_rule', {
        'session_id': session['id'], 'rule_id': rule.id,
        'expected_version': 1, 'reason': 'Cross-task requirement'}))
    assert promoted['task_id'] is None and promoted['points'] == ['Never lose refund']
    archived = unwrap(await server.call_tool('codeneuro_archive_requirement', {
        'session_id': session['id'], 'requirement_id': demand['id'],
        'expected_version': 1, 'summary': 'Agent confirmed completion'}))
    assert archived['status'] == 'archived'
    assert product.workspaces.list_tasks(agent, 'p')[0].status == 'archived'


@pytest.mark.asyncio
async def test_mcp_uses_authenticated_actor_not_model_supplied_identity(mcp):
    server, product, human, agent = mcp
    names = {tool.name: tool for tool in await server.list_tools()}
    task = names['codeneuro_submit_requirement']
    assert 'actor_id' not in task.input_schema['properties']
    assert 'project_id' not in names['codeneuro_get_context'].input_schema['properties']
    with pytest.raises(ToolError, match='forbidden'):
        await server.call_tool('codeneuro_list_tasks', {'project_id': 'q'})


@pytest.mark.asyncio
async def test_agent_governance_tools_create_draft_without_executing_tests(mcp):
    server, product, _, _ = mcp
    task = unwrap(await server.call_tool('codeneuro_create_task',
        {'project_id':'p', 'title':'Evidence task'}))
    session = unwrap(await server.call_tool('codeneuro_start_session',
        {'project_id':'p', 'workspace':'worktree-evidence', 'task_id':task['id']}))
    created = unwrap(await server.call_tool('codeneuro_create_task_rule', {
        'session_id':session['id'], 'title':'Task observation',
        'content_points':['Protect API'], 'scope_patterns':['src/**'],
        'reason':'Agent noticed an API constraint'}))
    assert created['rule']['status'] == 'draft'
    assert created['governance']['stage'] == 'observing'
    context = unwrap(await server.call_tool('codeneuro_get_context',
        {'session_id':session['id'], 'file_path':'src/api.py'}))
    assert created['rule']['id'] not in context['markdown']


@pytest.mark.asyncio
async def test_exact_same_catalogue_for_two_transports(mcp):
    server, product, _, agent = mcp
    remote = create_mcp(product, lambda ctx: agent, name='CodeNeuro HTTP')
    local = {tool.name: tool.input_schema for tool in await server.list_tools()}
    http = {tool.name: tool.input_schema for tool in await remote.list_tools()}
    assert local == http
