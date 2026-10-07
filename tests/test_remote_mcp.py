"""Actual authenticated Streamable HTTP MCP from a Windows-path client."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time

import httpx
import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from codeneuro.models import Project,Task,Rule
from codeneuro.storage import Storage


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


@pytest.mark.asyncio
async def test_real_streamable_http_auth_and_receipt(tmp_path):
    db=tmp_path/'hub.db'
    storage=Storage(str(db))
    storage.create_project(Project(id='p',name='project'))
    storage.create_task(Task(id='task',project_id='p',title='actual task'))
    storage.create_rule(Rule(id='short',project_id='p',task_id='task',title='path rule',
                            scope_patterns=['src/**'],content_points=['Keep the API input unchanged.']))
    storage.close()
    port=free_port();base=f'http://127.0.0.1:{port}'
    admin='test-admin-'+os.urandom(16).hex()
    env={**os.environ,'PYTHONPATH':str(__import__('pathlib').Path(__file__).resolve().parents[1]/'src'),
         'PYTHONDONTWRITEBYTECODE':'1','CODENEURO_API_TOKEN':admin,'CODENEURO_LLM_MODEL':'unconfigured-test-model'}
    process=subprocess.Popen([sys.executable,'-m','codeneuro.cli','serve','--host','127.0.0.1',
                              '--port',str(port),'--db',str(db)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        with httpx.Client(base_url=base,timeout=3,trust_env=False) as sync:
            for _ in range(80):
                if process.poll() is not None:
                    raise RuntimeError('Hub exited before readiness')
                try:
                    if sync.get('/api/health',headers={'Authorization':'Bearer '+admin}).status_code==200:break
                except httpx.ConnectError:
                    pass
                time.sleep(.1)
            else:raise TimeoutError('Hub did not become ready')
            assert sync.post('/mcp/',json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'anonymous','version':'1'}}}).status_code==401
            enrolled=sync.post('/api/clients',headers={'Authorization':'Bearer '+admin},json={'name':'Windows workstation','project_ids':['p']})
            assert enrolled.status_code==200,enrolled.text
            token=enrolled.json().pop('token')
            assert token.startswith('cn1_')
        async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+token},trust_env=False,follow_redirects=False) as hclient:
            async with streamable_http_client(base+'/mcp/',http_client=hclient) as (reader,writer,*_):
                async with ClientSession(reader,writer) as session:
                    await session.initialize()
                    names={tool.name for tool in (await session.list_tools()).tools}
                    assert {'codeneuro_start_session','codeneuro_get_context','codeneuro_rate_rule'}<=names
                    started=await session.call_tool('codeneuro_start_session',{'project_id':'p','workspace_path':r'C:\Work\repo',
                        'machine_name':'lab-pc','platform':'windows','task_id':'task','debug':True})
                    assert not started.is_error,started
                    sid=json.loads(started.content[0].text)['id']
                    found=await session.call_tool('codeneuro_get_context',{'session_id':sid,'file_path':r'C:\Work\repo\src\entry.py'})
                    assert not found.is_error,found
                    body=found.content[0].text
                    assert 'Keep the API input unchanged.' in body
                    import re
                    delivery=re.search(r'delivery_id=(delivery_[a-f0-9]+)',body)[1]
                    scored=await session.call_tool('codeneuro_rate_rule',{'session_id':sid,'delivery_id':delivery,'rule_id':'short','score':0,'reason':'Already learned within this actual session'})
                    assert not scored.is_error,scored
                    again=await session.call_tool('codeneuro_get_context',{'session_id':sid,'file_path':'src/entry.py'})
                    assert 'Keep the API input unchanged.' not in again.content[0].text
                    await session.call_tool('codeneuro_end_session',{'session_id':sid})
        with httpx.Client(base_url=base,timeout=3,trust_env=False) as sync:
            assert sync.get('/api/health',headers={'Authorization':'Bearer '+admin}).json()['verified_deliveries']==2
            assert sync.get('/api/projects',headers={'Authorization':'Bearer '+token}).status_code==401
        reopened=Storage(str(db));assert reopened.get_rule('short').hit_count==2;reopened.close()
    finally:
        process.terminate()
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        if process.stderr:
            process.stderr.close()
