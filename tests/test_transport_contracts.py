"""Real stdio/HTTP MCP and Web resources share one contract; no Session handle."""
from pathlib import Path
import json
import os
import re
import sys

import httpx
import httpx2
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from codeneuro.__main__ import create_http_app
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from helpers import initialize_database


@pytest.fixture
def configured(tmp_path):
    root = Path(__file__).resolve().parents[1]
    filename = str(tmp_path / 'transport.db')
    initialize_database(filename)
    uow = SqliteUnitOfWork(filename)
    product = Product(uow)
    product.workspaces.register_project(Actor('web', 'human'), 'p', 'test project')
    yield root, filename, product
    uow.dispose()


async def exercise_mcp(session):
    await session.initialize()
    tools = (await session.list_tools()).tools
    names = {item.name for item in tools}
    assert len(names) == 20 and 'codeneuro_get_delivery' in names
    assert not {'codeneuro_start_session', 'codeneuro_end_session'} & names
    assert all(item.output_schema is None for item in tools)

    async def call(name, args):
        result = await session.call_tool(name, args)
        assert not result.is_error, result
        assert result.structured_content is None and len(result.content) == 1
        return json.loads(result.content[0].text)

    assert (await call('codeneuro_list_projects', {}))[0]['id'] == 'p'
    parent = await call('codeneuro_requirement', {'project_id': 'p', 'action': 'create',
        'changes': {'title': 'Real transport', 'text': 'Goal received through MCP'}})
    task = await call('codeneuro_task', {'project_id': 'p', 'requirement_id': parent['id'], 'action': 'create',
        'changes': {'title': 'Implement feature'}})
    context = await call('codeneuro_get_context', {'project_id': 'p', 'task_id': task['id'],
        'priorities': ['P1'], 'files': ['src/pay.py'], 'request_id': 'transport-context',
        'source': {'workspace': 'C:/Synthetic/worktree', 'machine_name': 'fixture', 'platform': 'windows'}})
    assert 'protocol_version' not in context and 'sections' not in context
    assert context['task_refs'] == [[task['id'], 1]]
    assert await call('codeneuro_get_delivery', {'delivery_id': context['id']}) == context
    listed = await call('codeneuro_task', {'project_id': 'p', 'action': 'list', 'requirement_id': parent['id']})
    assert listed['next_cursor'] is None and listed['items'][0]['id'] == task['id']
    invalid = await session.call_tool('codeneuro_get_context', {'project_id': 'p', 'task_id': task['id'],
        'session_id': 'obsolete', 'priorities': ['P1'], 'files': ['src/pay.py']})
    assert invalid.is_error and 'session_id' in invalid.content[0].text


@pytest.mark.asyncio
async def test_real_stdio_mcp_without_session_lifecycle(configured):
    root, filename, _ = configured
    env = {key: value for key, value in os.environ.items() if not key.startswith('CODENEURO_')}
    env.update(PYTHONPATH=str(root / 'src'), PYTHONDONTWRITEBYTECODE='1')
    params = StdioServerParameters(command=sys.executable,
        args=['-B', '-m', 'codeneuro', 'mcp', '--db', filename], env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await exercise_mcp(session)


@pytest.mark.asyncio
async def test_real_streamable_http_mcp_matches_stdio(configured):
    _, _, product = configured
    app = create_http_app(product)
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='http://localhost')
    async with app.router.lifespan_context(app):
        async with http:
            async with streamable_http_client('http://localhost/mcp/', http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await exercise_mcp(session)


@pytest.mark.asyncio
async def test_web_requirement_task_resources_verification_acceptance_and_history(configured):
    _, _, product = configured
    app = create_http_app(product)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
            home = await client.get('/')
            assert home.status_code == 307 and home.headers['location'] == '/app/'
            workbench = await client.get('/app/')
            assert workbench.status_code == 200
            bundle = await client.get(re.search(r'/app/assets/[^" ]+\.js', workbench.text).group())
            assert bundle.status_code == 200 and 'hub-token' not in bundle.text and 'Bearer ' not in bundle.text
            body = {'changes': {'title': '档号要素维护', 'text': '完整档号业务'}, 'request_id': 'web-create'}
            created = await client.post('/api/projects/p/requirements', json=body)
            assert created.status_code == 200, created.text
            requirement = created.json()
            assert (await client.post('/api/projects/p/requirements', json=body)).json() == requirement
            changed = await client.post('/api/projects/p/requirements', json={**body, 'changes': {'title': 'Changed', 'text': 'Other'}})
            assert changed.status_code == 409
            task_response = await client.post('/api/projects/p/tasks', json={
                'requirement_id': requirement['id'], 'changes': {'title': '全宗号', 'acceptance_criteria': '不可重复'}})
            assert task_response.status_code == 200, task_response.text
            task = task_response.json()
            resource = f"/api/projects/p/tasks/{task['id']}"
            page = (await client.get(f"/api/projects/p/requirements/{requirement['id']}/tasks")).json()
            assert page['items'][0]['id'] == task['id'] and page['next_cursor'] is None
            stale = await client.patch(resource, json={'expected_version': 12, 'changes': {'title': 'Bad'}, 'reason': 'Stale'})
            assert stale.status_code == 409
            for status in ('testing', 'completed'):
                changes = {'status': status}
                if status == 'completed': changes['verification_summary'] = '唯一性和正常修改场景通过'
                response = await client.patch(resource, json={'expected_version': task['version'], 'changes': changes, 'reason': '推进验证'})
                assert response.status_code == 200, response.text
                task = response.json()
            parent_resource = f"/api/projects/p/requirements/{requirement['id']}"
            parent = (await client.get(parent_resource)).json()
            assert parent['status'] == 'accepting' and 'history' not in parent
            accepted = await client.patch(parent_resource, json={'expected_version': parent['version'],
                'changes': {'status': 'completed', 'completion_summary': '用户验收整体通过'}, 'reason': '用户确认'})
            assert accepted.status_code == 200 and accepted.json()['status'] == 'completed'
            history = (await client.get(resource + '/versions?limit=1')).json()
            assert len(history['items']) == 1 and history['next_cursor'] == 1
            next_history = (await client.get(resource + '/versions?limit=1&cursor=1')).json()
            assert next_history['items'][0]['version'] == 2
            ledger = (await client.get('/api/projects/p/ledger')).json()
            assert ledger['counts']['requirements']['completed'] == 1 and ledger['counts']['tasks']['completed'] == 1
            assert ledger['requirements'][0]['progress'] == {'total': 1, 'completed': 1}
            assert (await client.post(resource + '/requirements/x/archive', json={'summary': 'Old semantics'})).status_code == 404
            assert (await client.post('/api/projects/p/tasks', json={'title': 'Old flat task'})).status_code == 422
            invalid_null = await client.patch(resource, json={'expected_version': task['version'], 'changes': {'title': None}, 'reason': 'No'})
            assert invalid_null.status_code == 422


@pytest.mark.asyncio
async def test_http_mcp_accepts_direct_project_reads(configured):
    _, _, product = configured
    app = create_http_app(product)
    headers = {'accept': 'application/json, text/event-stream', 'content-type': 'application/json'}
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'codeneuro_list_projects', 'arguments': {}}}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
            response = await client.post('/mcp/', headers=headers, json=body)
    assert response.status_code == 200 and response.json()['result']['isError'] is False
    assert 'structuredContent' not in response.json()['result']
    assert len(response.json()['result']['content']) == 1
