"""Real stdio protocol and authenticated ASGI streamable-HTTP MCP boundaries."""
from pathlib import Path
import json
import os
import subprocess
import sys

import httpx
import httpx2
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from codeneuro.__main__ import create_http_app
from codeneuro.adapters.mcp.identity import Identities
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product

SECRET = 'development-transport-credential-very-long'


@pytest.fixture
def configured(tmp_path):
    root = Path(__file__).resolve().parents[1]
    filename = str(tmp_path / 'new.db')
    subprocess.run([sys.executable, '-B', '-m', 'codeneuro',
                    'migrate', '--db', filename], cwd=root,
                   capture_output=True, text=True, check=True)
    uow = SqliteUnitOfWork(filename)
    product = Product(uow)
    product.workspaces.register_project(Actor('admin', frozenset({'p'}), 'human'), 'p', 'test project')
    declarations = [{'token_env': 'CODENEURO_CLIENT_TOKEN', 'actor_id': 'agent', 'project_ids': ['p']}]
    yield root, filename, product, Identities(declarations, {'CODENEURO_CLIENT_TOKEN': SECRET}), declarations
    uow.dispose()


@pytest.mark.asyncio
async def test_real_stdio_mcp_uses_one_catalogue_and_token_scopes(configured):
    root, filename, product, _, declarations = configured
    env = {**os.environ, 'CODENEURO_CLIENTS': json.dumps(declarations),
           'CODENEURO_CLIENT_TOKEN': SECRET, 'CODENEURO_TOKEN': SECRET,
           'PYTHONPATH': str(root / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
    params = StdioServerParameters(command=sys.executable,
        args=['-B', '-m', 'codeneuro', 'mcp', '--db', filename], env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {'codeneuro_list_tasks', 'codeneuro_get_context'} <= {item.name for item in tools.tools}
            projects = await session.call_tool('codeneuro_list_projects', {})
            assert json.loads(projects.content[0].text) == [{'id': 'p', 'name': 'test project', 'rule_revision': 0}]
            task = await session.call_tool('codeneuro_create_task', {'project_id': 'p', 'title': 'Real MCP'})
            assert json.loads(task.content[0].text)['title'] == 'Real MCP'


@pytest.mark.asyncio
async def test_web_api_intake_archive_and_ledger_use_same_workflows(configured):
    _, _, product, _, _ = configured
    human_secret = 'human-console-credential-very-long'
    identities = Identities([{'token_env': 'CODENEURO_HUMAN_TOKEN',
        'actor_id': 'admin', 'project_ids': ['p', 'q'], 'role': 'human'}],
        {'CODENEURO_HUMAN_TOKEN': human_secret})
    app = create_http_app(product, identities)
    auth = {'authorization': 'Bearer ' + human_secret}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://localhost') as client:
            denied = await client.get('/api/projects')
            assert denied.status_code == 401
            created_project = await client.post('/api/projects', headers=auth,
                json={'id': 'q', 'name': 'Second project'})
            assert created_project.status_code == 200 and created_project.json()['id'] == 'q'
            workbench = await client.get('/app/')
            assert workbench.status_code == 200 and 'CodeNeuro' in workbench.text
            first = await client.post('/api/projects/p/requirements', headers=auth,
                json={'text':'Refund must be idempotent', 'request_id':'web-1', 'title':'Refund'})
            assert first.status_code == 200, first.text
            retry = await client.post('/api/projects/p/requirements', headers=auth,
                json={'text':'Refund must be idempotent', 'request_id':'web-1', 'title':'Refund'})
            assert retry.json()['id'] == first.json()['id']
            changed = await client.post('/api/projects/p/requirements', headers=auth,
                json={'text':'Different request', 'request_id':'web-1', 'title':'Refund'})
            assert changed.status_code == 409
            task = (await client.get('/api/projects/p/tasks', headers=auth)).json()[0]
            second = await client.post('/api/projects/p/requirements', headers=auth,
                json={'text':'Cover chargeback', 'request_id':'web-2', 'task_id':task['id']})
            assert second.status_code == 200 and second.json()['task_id'] == task['id']
            task_url = f"/api/projects/p/tasks/{task['id']}"
            current = (await client.get('/api/projects/p/tasks', headers=auth)).json()[0]
            paused = await client.post(task_url + '/pause', headers=auth,
                json={'expected_revision':current['revision'],'reason':'Wait for upstream'})
            assert paused.status_code == 200 and paused.json()['status'] == 'paused'
            resumed = await client.post(task_url + '/resume', headers=auth,
                json={'expected_revision':paused.json()['revision'],'reason':'Unblocked'})
            assert resumed.status_code == 200 and resumed.json()['status'] == 'active'
            archive = lambda req: f"/api/projects/p/tasks/{task['id']}/requirements/{req}/archive"
            result = await client.post(archive(first.json()['id']), headers=auth,
                json={'expected_version':1,'summary':'Agent confirmed first requirement'})
            assert result.status_code == 200
            assert (await client.get('/api/projects/p/tasks', headers=auth)).json()[0]['status'] == 'active'
            result = await client.post(archive(second.json()['id']), headers=auth,
                json={'expected_version':1,'summary':'Agent confirmed second requirement'})
            assert result.status_code == 200, result.text
            ledger = (await client.get('/api/projects/p/ledger', headers=auth)).json()
            assert ledger['tasks'][0]['status'] == 'archived'
            assert {r['status'] for r in ledger['requirements']} == {'archived'}
            assert sum(e['action'] == 'task.completed' for e in ledger['events']) == 1


@pytest.mark.asyncio
async def test_real_streamable_http_mcp_matches_stdio_business_tools(configured):
    _, _, product, identities, _ = configured
    app = create_http_app(product, identities)
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
        base_url='http://localhost', headers={'authorization': 'Bearer ' + SECRET})
    async with app.router.lifespan_context(app):
        async with http:
            async with streamable_http_client('http://localhost/mcp/', http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    names = {item.name for item in (await session.list_tools()).tools}
                    assert {'codeneuro_get_context','codeneuro_archive_requirement'} <= names
                    result = await session.call_tool('codeneuro_list_projects', {})
                    assert not result.is_error
                    assert json.loads(result.content[0].text)[0]['id'] == 'p'
                    created = await session.call_tool('codeneuro_create_task',
                        {'project_id': 'p', 'title': 'Remote Task'})
                    task = json.loads(created.content[0].text)
                    opened = await session.call_tool('codeneuro_start_session', {
                        'project_id': 'p', 'workspace': 'C:/Work/Repo', 'task_id': task['id'],
                        'machine_name': 'office', 'platform': 'windows', 'repo_identity': 'git-common-id'})
                    assert json.loads(opened.content[0].text)['worktree_id'].startswith('wt_')


@pytest.mark.asyncio
async def test_http_mcp_denies_missing_wrong_and_wrong_project_credentials(configured):
    _, _, product, identities, _ = configured
    app = create_http_app(product, identities)
    headers = {'accept': 'application/json, text/event-stream', 'content-type': 'application/json'}
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'codeneuro_list_projects', 'arguments': {}}}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://localhost') as client:
            no_token = await client.post('/mcp/', headers=headers, json=body)
            invalid = await client.post('/mcp/', headers={**headers,
                'authorization': 'Bearer invalid-invalid-invalid-token'}, json=body)
            allowed = await client.post('/mcp/', headers={**headers,
                'authorization': 'Bearer ' + SECRET}, json=body)
    for denied in (no_token, invalid):
        assert denied.status_code == 200, denied.text
        assert denied.json()['result']['isError'] is True
        assert 'test project' not in denied.text
    assert allowed.status_code == 200 and allowed.json()['result']['isError'] is False
    assert 'test project' in allowed.text
