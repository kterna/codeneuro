"""Exercise the integrated workbench in Chromium against real isolated domain records.

This is browser acceptance, not a substitute for actual coding-agent experiments.
No production service, invented metrics, or intercepted API responses are used.
"""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from websockets.sync.client import connect
from browser_smoke import port, wait


class Browser:
    def __init__(self, target):
        self.ws = connect(target, max_size=None, legacy=True)
        self.serial = 0
        self.errors = []
        self.call('Runtime.enable')
        self.call('Page.enable')
        self.call('Network.enable')
        self.resize(1540, 1120)

    def call(self, method, params=None):
        self.serial += 1
        self.ws.send(json.dumps({'id': self.serial, 'method': method, 'params': params or {}}))
        while True:
            response = json.loads(self.ws.recv(timeout=20))
            if response.get('method') == 'Runtime.exceptionThrown':
                self.errors.append(response['params'])
            if response.get('id') == self.serial:
                if 'error' in response:
                    raise RuntimeError(response['error'])
                return response.get('result', {})

    def js(self, source):
        result = self.call('Runtime.evaluate', {'expression': source, 'returnByValue': True, 'awaitPromise': True})
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'])
        return result.get('result', {}).get('value')

    def ready(self, source, timeout=25):
        return wait(lambda: self.js(source), timeout=timeout)

    def click(self, label, scope='document'):
        expression = f"Array.from({scope}.querySelectorAll('button')).find(b=>(b.textContent.trim()==={json.dumps(label)} || b.getAttribute('aria-label')==={json.dumps(label)}) && !b.disabled)"
        self.ready(f'Boolean({expression})')
        self.js(f'({expression}).click()')

    def navigate(self, label):
        self.click(label, 'document.getElementById("navigation")')
        self.ready(f"document.getElementById('title').textContent==={json.dumps(label)} && document.getElementById('content').getAttribute('aria-busy')==='false'")

    def fill(self, values):
        for key, value in values.items():
            self.js(f"document.querySelector('#editor-fields [name={key}]').value={json.dumps(value)}")
        self.js("document.querySelector('#editor-form button[type=submit]').click()")
        self.ready("!document.getElementById('editor').open")
        self.ready("document.getElementById('content').getAttribute('aria-busy')==='false'")

    def resize(self, width, height):
        self.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False})

    def screenshot(self, path):
        result = self.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
        path.write_bytes(base64.b64decode(result['data']))


@contextmanager
def harness(args):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    processes = []
    with tempfile.TemporaryDirectory(prefix='codeneuro-workbench-') as temp:
        root = Path(temp)
        http, debug = port(), port()
        origin = f'http://127.0.0.1:{http}'
        env = {**os.environ, 'PYTHONPATH': str(args.repo / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
        # Provider-free browser acceptance verifies an honest failed analysis state.
        # Successful live-provider analysis has its separate actual coding validation.
        for name in tuple(env):
            if name.startswith('CODENEURO_'):
                env.pop(name)
        log = (root / 'process.log').open('w+')

        def api(path, method='GET', body=None):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(origin + path, data=data, method=method,
                                         headers={'Content-Type': 'application/json'} if data else {})
            try:
                with opener.open(req, timeout=10) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                raise AssertionError(f'{method} {path}: {error.code} {error.read().decode()}') from error

        try:
            processes.append(subprocess.Popen([sys.executable, '-m', 'codeneuro.cli', 'serve', '--port', str(http), '--db', str(root/'test.db')], env=env, stdout=log, stderr=log))
            wait(lambda: api('/api/health'))
            processes.append(subprocess.Popen([args.chromium, '--headless', '--no-sandbox', '--disable-gpu', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run', '--password-store=basic', f'--user-data-dir={root/"profile"}', f'--remote-debugging-port={debug}', 'about:blank'], stdout=log, stderr=log))
            def targets():
                with opener.open(f'http://127.0.0.1:{debug}/json/list', timeout=2) as r:
                    return json.load(r)
            target = wait(targets)[0]
            browser = Browser(target['webSocketDebuggerUrl'])
            yield root, origin, api, browser
            assert not browser.errors, browser.errors
            browser.ws.close()
        except BaseException:
            log.flush();log.seek(0)
            print(log.read()[-6000:], file=sys.stderr)
            raise
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait()
            log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chromium', required=True)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    flows = []
    with harness(args) as (root, origin, api, b):
        workspace = root/'workspace'
        (workspace/'src').mkdir(parents=True)
        (workspace/'src/cache.py').write_text('from collections import OrderedDict\n\ndef copy_input(value):\n    """Return a separate input mapping."""\n    return dict(value)\n')
        (workspace/'README.md').write_text('# Isolated browser acceptance workspace\n')
        project = api('/api/projects', 'POST', {'name':'工作台真实浏览器验收', 'root_paths':[str(workspace)]})
        pid = project['id']
        prefix = '/api/projects/' + pid
        task = api(prefix+'/tasks', 'POST', {'title':'缓存接口需求', 'description':'输入数据保持不变，缓存具备明确生命周期。'})
        other = api(prefix+'/tasks', 'POST', {'title':'并行工作区需求', 'description':'验证任务隔离和安全换绑。'})
        contract = api(prefix+'/rules', 'POST', {'title':'缓存必须保留调用者输入', 'lifecycle':'long_term', 'priority':'P0', 'scope_patterns':['src/**'], 'content_points':['Copy input before editing.']})
        transient = api(prefix+'/rules', 'POST', {'title':'本次需求的缓存有效期', 'task_id':task['id'], 'lifecycle':'short_term', 'priority':'P1', 'scope_patterns':['src/cache.py'], 'content_points':['Expire values after 60 seconds.']})
        session = api('/api/agent/sessions', 'POST', {'project_id':pid, 'workspace_path':str(workspace), 'task_id':task['id'], 'agent_client':'Chromium acceptance fixture', 'debug':True})
        api(prefix+'/index/local', 'POST', {'worktree_id':session['worktree_id']})
        deliveries = []
        for i, score in enumerate([0,0,1,1,4,5]):
            delivery = api('/api/agent/context', 'POST', {'session_id':session['id'], 'file_path':'src/cache.py', 'request_id':f'browser-sample-{i}'})
            deliveries.append(delivery)
            api('/api/agent/feedback', 'POST', {'session_id':session['id'], 'delivery_id':delivery['delivery_id'], 'rule_id':contract['id'], 'score':score, 'reason':f'Isolated acceptance sample {i}; validates score {score} display.'})
        assert api('/api/health')['verified_deliveries'] == 6
        issue = api(prefix+'/issues', 'POST', {'id':'browser_review_issue', 'project_id':pid, 'issue_type':'rule_outdated', 'title':'明确缓存契约的复制语义', 'description':'人工验收发现条款需要明确浅复制。', 'file_path':'src/cache.py', 'related_rule_ids':[contract['id']], 'suggested_action':'Review and clarify the existing rule. This text must never execute.', 'source':'human'})
        b.call('Page.navigate', {'url':origin})
        b.ready("document.getElementById('health').textContent.includes('服务正常') && document.getElementById('content').getAttribute('aria-busy')==='false'")
        b.ready("document.getElementById('live-status').textContent.includes('已连接')")
        b.js(f"document.querySelector('[aria-label=目录任务范围]').value={json.dumps(task['id'])};document.querySelector('[aria-label=目录任务范围]').dispatchEvent(new Event('change'))")
        b.ready("document.querySelector('.tree-content details')!==null && document.getElementById('content').getAttribute('aria-busy')==='false'")
        b.js("Array.from(document.querySelectorAll('.tree-content details')).forEach(d=>d.open=true)")
        b.js("document.querySelector('[data-path=\"src/cache.py\"]').click()")
        b.ready("document.getElementById('focus-inspector').textContent.includes('缓存必须保留调用者输入') && document.getElementById('focus-inspector').textContent.includes('copy_input')")
        assert b.js("document.getElementById('focus-inspector').textContent.includes('Chromium acceptance fixture')")
        assert b.js("document.getElementById('focus-inspector').textContent.includes('本次需求的缓存有效期')")
        b.screenshot(args.output/'focus-inspector.png')
        flows.append('real_tree_focus_inheritance_graph_delivery_trace')
        b.resize(390, 844)
        assert b.js('document.documentElement.scrollWidth <= window.innerWidth + 1'), 'Mobile layout overflows viewport'
        b.screenshot(args.output/'mobile-focus.png')
        b.resize(1540,1120)
        flows.append('responsive_mobile_focus')
        b.call('Input.dispatchKeyEvent', {'type':'keyDown','key':'k','code':'KeyK','modifiers':2})
        b.ready("document.getElementById('palette').open")
        b.js("document.getElementById('palette-input').value='反馈与问题';document.getElementById('palette-input').dispatchEvent(new Event('input'))")
        b.call('Input.dispatchKeyEvent', {'type':'keyDown','key':'Enter','code':'Enter'})
        b.ready("document.getElementById('title').textContent==='反馈与问题' && document.querySelector('table')!==null")
        flows.append('keyboard_command_palette_search_and_navigation')
        b.click('下钻样本')
        b.ready("document.getElementById('detail').textContent.includes('6 个当前载入样本')")
        for delivery in deliveries:
            assert b.js(f"document.getElementById('detail').textContent.includes({json.dumps(delivery['delivery_id'])})")
        b.click('×', 'document.getElementById("detail")')
        assert b.js("document.getElementById('content').textContent.includes('重复 2') && document.getElementById('content').textContent.includes('无关 2')")
        b.screenshot(args.output/'debug-matrix.png')
        flows.append('version_score_matrix_noise_fatigue_receipt_drilldown')
        b.click('审阅并采纳建议')
        b.fill({'action':'update', 'rule_id':contract['id'], 'title':contract['title'], 'priority':'P0', 'scopes':'src/**', 'points':'Shallow-copy input before editing.', 'reason':'Browser reviewer checked the actual copy_input implementation.'})
        updated = next(r for r in api(prefix+'/rules') if r['id']==contract['id'])
        assert updated['version']==2 and updated['content_points']==['Shallow-copy input before editing.']
        assert next(i for i in api(prefix+'/issues') if i['id']==issue['id'])['status']=='resolved'
        flows.append('reviewed_atomic_issue_change_and_version')
        b.navigate('需求与生命周期')
        scope=f'document.querySelector("[data-task-id=\\"{task["id"]}\\"]")'
        b.click('暂停', scope)
        b.ready(f"document.querySelector('[data-status=paused] [data-task-id=\"{task['id']}\"]')!==null")
        assert not api(f'/api/context?project_id={pid}&task_id={task["id"]}&file_path=src/cache.py')['short_term_rules']
        b.click('恢复', scope)
        b.ready(f"document.querySelector('[data-status=active] [data-task-id=\"{task['id']}\"]')!==null")
        assert api(f'/api/context?project_id={pid}&task_id={task["id"]}&file_path=src/cache.py')['short_term_rules']
        flows.append('pause_resume_swimlane_and_actual_context_effect')
        live_task=api(prefix+'/tasks','POST',{'title':'SSE 外部新增需求'})
        b.ready(f"document.querySelector('[data-task-id=\"{live_task['id']}\"]')!==null")
        b.call('Network.emulateNetworkConditions',{'offline':True,'latency':0,'downloadThroughput':0,'uploadThroughput':0})
        offline_task=api(prefix+'/tasks','POST',{'title':'断线期间新增需求'})
        b.call('Network.emulateNetworkConditions',{'offline':False,'latency':0,'downloadThroughput':-1,'uploadThroughput':-1})
        b.ready(f"document.querySelector('[data-task-id=\"{offline_task['id']}\"]')!==null",timeout=40)
        assert b.js(f"document.querySelectorAll('[data-task-id=\"{offline_task['id']}\"]').length===1")
        b.screenshot(args.output/'task-swimlanes.png')
        flows.append('sse_live_update_disconnect_reconnect_without_duplicate')
        b.navigate('工作区与会话')
        b.click('安全换绑任务')
        b.fill({'task_id':other['id']})
        bound=next(s for s in api(prefix+'/sessions') if s['id']==session['id'])
        assert bound['task_id']==other['id'] and bound['binding_revision']>session.get('binding_revision',0)
        assert b.js("document.getElementById('content').textContent.includes('src/cache.py')")
        flows.append('workspace_latest_delivery_and_safe_session_binding')
        b.navigate('发现与治理')
        b.click('＋ 提交治理变更')
        b.fill({'action':'update','rule_id':contract['id'],'points':'Always shallow-copy input before editing.','reason':'Reviewed evidence from the actual sample function.'})
        b.click('审阅并应用变更')
        b.fill({'reason':'Actual isolated-browser review of scope and target version.'})
        assert next(r for r in api(prefix+'/rules') if r['id']==contract['id'])['version']==3
        flows.append('governance_proposal_review_apply')
        b.navigate('PRD 与代码认知')
        b.click('＋ 分析 PRD')
        b.fill({'task_id':task['id'],'worktree_id':session['worktree_id'],'text':'为当前缓存接口增加按调用方隔离的过期机制，并保持输入数据不变。'})
        b.ready("document.getElementById('content').textContent.includes('分析未完成')",timeout=40)
        assert b.js("document.getElementById('content').textContent.includes('重试分析')")
        flows.append('durable_analysis_job_honest_provider_error')
        b.click('导出规则')
        b.fill({'format':'cursor','task_id':task['id'],'out_dir':str(workspace)})
        assert list((workspace/'.cursor/rules').glob('*.mdc'))
        flows.append('reviewed_static_export_writes_actual_files')
        assert api('/api/health')['verified_deliveries']==6, 'Browsing and preview must never fabricate usage'
        flows.append('all_browser_reads_preserve_verified_delivery_count')
        b.navigate('变更记录')
        b.ready("document.getElementById('content').textContent.includes('rule')")
        ids=b.js("Array.from(document.querySelectorAll('[data-event-id]')).map(e=>e.dataset.eventId)")
        assert len(ids)==len(set(ids))
        flows.append('durable_audit_has_unique_event_sequences')
    report={'status':'passed','kind':'isolated_real_browser_acceptance','flows':flows,'javascript_errors':0,'coding_agent_evidence':False}
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
