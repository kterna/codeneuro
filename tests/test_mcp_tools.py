"""Actual JSON-RPC over stdio, with an independent server process and database."""
import json
import os
import re
import sys
from pathlib import Path
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from codeneuro.models import Project, Task, Rule, Lifecycle, Priority
from codeneuro.storage import Storage


def text(result):
    assert not result.is_error, result
    return '\n'.join(block.text for block in result.content if hasattr(block,'text'))


@pytest.mark.asyncio
async def test_mcp_protocol_delivery_feedback_and_findings(tmp_path):
    db=str(tmp_path/'mcp.db')
    store=Storage(db)
    store.create_project(Project(id='p',name='MCP test',root_paths=[str(tmp_path)]))
    store.create_task(Task(id='t',project_id='p',title='feature'))
    store.create_rule(Rule(id='r',project_id='p',task_id='t',title='cache contract',scope_patterns=['src/**'],content_points=['Never mutate the caller input.']))
    store.create_rule(Rule(id='global',project_id='p',lifecycle=Lifecycle.LONG_TERM,priority=Priority.P0,title='security',scope_patterns=['**'],content_points=['Do not log secrets.']))
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src'),'PYTHONDONTWRITEBYTECODE':'1'}
    params=StdioServerParameters(command=sys.executable,args=['-m','codeneuro.cli','mcp','--db',db,'--debug'],env=env)
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            names={t.name for t in (await client.list_tools()).tools}
            assert {'codeneuro_start_session','codeneuro_get_context','codeneuro_rate_rule','codeneuro_report_issue'}<=names
            started=json.loads(text(await client.call_tool('codeneuro_start_session',{'project_id':'p','workspace_path':str(tmp_path),'task_id':'t'})))
            sid=started['id']
            result=text(await client.call_tool('codeneuro_get_context',{'session_id':sid,'file_path':'src/cache.py','request_id':'call1'}))
            assert 'Never mutate the caller input.' in result
            did=re.search(r'delivery_id=(delivery_[a-f0-9]+)',result)[1]
            score=text(await client.call_tool('codeneuro_rate_rule',{'session_id':sid,'delivery_id':did,'rule_id':'r','score':0}))
            assert json.loads(score)['score']==0
            next_result=text(await client.call_tool('codeneuro_get_context',{'session_id':sid,'file_path':'src/cache.py'}))
            assert 'Never mutate the caller input.' not in next_result
            assert 'Do not log secrets.' in next_result
            finding=json.loads(text(await client.call_tool('codeneuro_record_finding',{'session_id':sid,'target_path':'src/cache.py','finding_text':'A shallow copy still aliases nested lists.'})))
            assert finding['source']=='agent' and finding['session_id']==sid
            issue=json.loads(text(await client.call_tool('codeneuro_report_issue',{'session_id':sid,'issue_type':'scope_missing','title':'nested cache','description':'Need a separate nested-list rule','file_path':'src/cache.py','related_rule_ids':['r']})))
            assert issue['source']=='agent'
            denied=await client.call_tool('codeneuro_patch_rule',{'session_id':sid,'rule_id':'global','action':'revoke','reason':'try','expected_version':1})
            assert denied.is_error
            text(await client.call_tool('codeneuro_end_session',{'session_id':sid}))
    assert store.get_rule('r').eval_count==1
    assert store.conn.execute('SELECT count(*) FROM context_deliveries').fetchone()[0]==2
    store.close()


@pytest.mark.asyncio
async def test_debug_tools_not_exposed_by_default(tmp_path):
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src'),'CODENEURO_DEBUG':'0','CODETOKEN_DEBUG':'0'}
    params=StdioServerParameters(command=sys.executable,args=['-m','codeneuro.cli','mcp','--db',str(tmp_path/'plain.db')],env=env)
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            names={t.name for t in (await client.list_tools()).tools}
            assert 'codeneuro_rate_rule' not in names
            assert 'codeneuro_report_issue' not in names
