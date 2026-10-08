"""Real local stdio MCP -> authenticated loopback Hub -> actual file and test evidence."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from codeneuro.models import Project, Rule, Task
from codeneuro.storage import Storage


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def result_payload(reply):
    assert not reply.is_error,reply
    return json.loads(reply.content[0].text)


@pytest.mark.asyncio
async def test_workstation_mcp_reads_rates_tests_and_blocks_unreviewed_edit(tmp_path):
    workspace=tmp_path/'repo';(workspace/'src').mkdir(parents=True)
    source=workspace/'src'/'sample.py';source.write_text('value = 1\n',encoding='utf-8')
    (workspace/'test_sample.py').write_text('import unittest\nfrom src.sample import value\n\nclass TestSample(unittest.TestCase):\n    def test_value(self): self.assertEqual(value, 1)\n',encoding='utf-8')
    db=tmp_path/'hub.db';store=Storage(str(db))
    store.create_project(Project(id='p',name='real workspace',root_paths=[str(workspace)]))
    store.create_task(Task(id='task',project_id='p',title='actual change'))
    store.create_rule(Rule(id='contract',project_id='p',task_id='task',title='source rule',
                           scope_patterns=['src/**'],content_points=['Keep the sample value observable.']))
    store.close()
    port=free_port();base=f'http://127.0.0.1:{port}'
    admin='admin-'+os.urandom(16).hex()
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src'),
         'PYTHONDONTWRITEBYTECODE':'1','CODENEURO_API_TOKEN':admin}
    for key in tuple(env):
        if key.startswith('CODENEURO_LLM_'):
            env.pop(key)
    server=subprocess.Popen([sys.executable,'-m','codeneuro.cli','serve','--host','127.0.0.1',
                             '--port',str(port),'--db',str(db)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        with httpx.Client(base_url=base,timeout=3,trust_env=False) as http:
            for _ in range(80):
                if server.poll() is not None:raise RuntimeError('Server exited before readiness')
                try:
                    if http.get('/api/health',headers={'Authorization':'Bearer '+admin}).status_code==200:break
                except httpx.ConnectError:pass
                time.sleep(.1)
            else:raise TimeoutError('Server not ready')
            response=http.post('/api/clients',headers={'Authorization':'Bearer '+admin},
                               json={'name':'local stdio acceptance','project_ids':['p']})
            assert response.status_code==200,response.text
            token=response.json()['token']
        (workspace/'.codeneuro.json').write_text(json.dumps({'hub_url':base,'project_id':'p',
            'active_task':'task','token_env':'CODENEURO_TOKEN'}),encoding='utf-8')
        mcp_env={**env,'CODENEURO_HUB_URL':base,'CODENEURO_TOKEN':token}
        params=StdioServerParameters(command=sys.executable,args=['-m','codeneuro.cli','mcp','--config',
            str(workspace/'.codeneuro.json'),'--workspace',str(workspace),'--debug'],env=mcp_env)
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as mcp:
                await mcp.initialize()
                names={tool.name for tool in (await mcp.list_tools()).tools}
                assert {'codeneuro_read_file','codeneuro_edit_file','codeneuro_run_tests','codeneuro_rate_rule'}<=names
                read_result=result_payload(await mcp.call_tool('codeneuro_read_file',{'file_path':'src/sample.py'}))
                assert read_result['content']=='value = 1\n'
                assert 'Keep the sample value observable.' in read_result['context']['rendered_markdown']
                did=read_result['delivery_id']
                scored=result_payload(await mcp.call_tool('codeneuro_rate_rule',{'delivery_id':did,
                    'rule_id':'contract','score':5,'reason':'The rule identified the behavior verified by this test.'}))
                assert scored['score']==5
                edit_result=result_payload(await mcp.call_tool('codeneuro_edit_file',{'file_path':'src/sample.py',
                    'new_content':'value = 2\n','expected_sha256':read_result['sha256'],
                    'plan':'Change the example value after checking the task contract.'}))
                assert edit_result['written'] is False and edit_result['status']=='review_required'
                assert source.read_text()=='value = 1\n'
                test_result=result_payload(await mcp.call_tool('codeneuro_run_tests',{'command':[sys.executable,'-m','unittest','test_sample'],
                    'paths':['src/sample.py'],'timeout_seconds':30}))
                assert test_result['recorded'] is True and test_result['exit_code']==0
                assert test_result['test_run']['exit_code']==0
                assert test_result['test_run']['command'][1:]==['-m','unittest','test_sample']
                assert result_payload(await mcp.call_tool('codeneuro_session_cleanup',{'close':True}))['closed']
        reopened=Storage(str(db))
        assert reopened.get_rule('contract').eval_count==1
        assert reopened.conn.execute('SELECT count(*) FROM context_deliveries').fetchone()[0]>=3
        assert reopened.conn.execute('SELECT count(*) FROM governance_test_runs').fetchone()[0]==1
        assert reopened.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        reopened.close()
    finally:
        server.terminate()
        try:server.wait(timeout=8)
        except subprocess.TimeoutExpired:server.kill();server.wait()
        if server.stderr:server.stderr.close()
