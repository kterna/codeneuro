"""Real Chromium acceptance using an isolated database/profile. Never visits production."""
import argparse
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from websockets.sync.client import connect


def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def wait(fn,timeout=25):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            result=fn()
            if result:return result
        except (OSError,ValueError):pass
        time.sleep(.1)
    raise TimeoutError('Condition not met')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--chromium',required=True);parser.add_argument('--screenshot',required=True)
    args=parser.parse_args();repo=Path(__file__).resolve().parents[1]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(url):
        with opener.open(url,timeout=2) as r:return json.load(r)
    processes=[]
    with tempfile.TemporaryDirectory(prefix='codeneuro-browser-') as temp:
        root=Path(temp);http,debug=port(),port()
        env={**os.environ,'PYTHONPATH':str(repo/'src'),'PYTHONDONTWRITEBYTECODE':'1'}
        env.pop('CODENEURO_API_TOKEN',None)
        log=(root/'process.log').open('w+')
        try:
            processes.append(subprocess.Popen([sys.executable,'-m','codeneuro.cli','serve','--port',str(http),'--db',str(root/'test.db')],env=env,stdout=log,stderr=log))
            wait(lambda:get(f'http://127.0.0.1:{http}/api/health'))
            processes.append(subprocess.Popen([args.chromium,'--headless','--no-sandbox','--disable-gpu','--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--password-store=basic',f'--user-data-dir={root/"profile"}',f'--remote-debugging-port={debug}','about:blank'],stdout=log,stderr=log))
            targets=wait(lambda:get(f'http://127.0.0.1:{debug}/json/list'))
            ws=connect(targets[0]['webSocketDebuggerUrl'],max_size=None,legacy=True)
            serial=0;errors=[]
            def cdp(method,params=None):
                nonlocal serial
                serial+=1;ws.send(json.dumps({'id':serial,'method':method,'params':params or {}}))
                while True:
                    response=json.loads(ws.recv(timeout=15))
                    if response.get('method')=='Runtime.exceptionThrown':errors.append(response['params'])
                    if response.get('id')==serial:
                        if 'error' in response:raise RuntimeError(response['error'])
                        return response.get('result',{})
            def js(source):
                result=cdp('Runtime.evaluate',{'expression':source,'returnByValue':True,'awaitPromise':True})
                if 'exceptionDetails' in result:raise RuntimeError(result['exceptionDetails'])
                return result.get('result',{}).get('value')
            def click(text,scope='document'):
                wait(lambda:js(f"Array.from({scope}.querySelectorAll('button')).some(b=>b.textContent.trim()==={json.dumps(text)} && !b.disabled)"))
                js(f"Array.from({scope}.querySelectorAll('button')).find(b=>b.textContent.trim()==={json.dumps(text)}).click()")
            def fill(values):
                for name,value in values.items():js(f"document.querySelector('#editor-fields [name={name}]').value={json.dumps(value)}")
                js("document.querySelector('#editor-form button[type=submit]').click()")
                wait(lambda:js("!document.getElementById('editor').open"))
            cdp('Runtime.enable');cdp('Page.enable');cdp('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1080,'deviceScaleFactor':1,'mobile':False})
            cdp('Page.navigate',{'url':f'http://127.0.0.1:{http}/'})
            wait(lambda:js("document.getElementById('health')?.textContent.includes('服务正常')"))
            click('＋ 注册项目');fill({'name':'真实浏览器验收','roots':str(root),'description':'isolated browser acceptance'})
            wait(lambda:js("document.getElementById('project').options.length===1"))
            click('需求与生命周期');wait(lambda:js("document.getElementById('title').textContent==='需求与生命周期'"))
            click('＋ 新建任务');fill({'title':'缓存需求','description':'Verify a real temporary rule lifecycle'})
            wait(lambda:js("document.querySelectorAll('#content article').length===1"))
            click('范围规则');wait(lambda:js("document.getElementById('title').textContent==='范围规则'"))
            click('＋ 新建规则')
            task=js("document.querySelector('#editor-fields select[name=task_id]').options[1].value")
            fill({'title':'缓存不能修改输入','task_id':task,'priority':'P1','scopes':'src/**','points':'Never mutate the caller input.','reason':'browser acceptance'})
            wait(lambda:js("document.querySelectorAll('#content article').length===1"))
            click('编辑');fill({'title':'缓存不能修改输入','task_id':task,'priority':'P1','scopes':'src/**','points':'Copy input before editing.','reason':'clarify contract'})
            wait(lambda:js("document.querySelector('#content').textContent.includes('v2')"))
            click('上下文预览');wait(lambda:js("document.querySelector('#content input')!==null"))
            js("document.querySelector('#content input').value='src/cache.py'")
            js(f"document.querySelector('#content select').value={json.dumps(task)}")
            click('预览上下文');wait(lambda:js("document.querySelector('#content pre')?.textContent.includes('Copy input before editing.')"))
            assert get(f'http://127.0.0.1:{http}/api/stats')['total_hits']==0
            click('需求与生命周期');wait(lambda:js("document.querySelectorAll('#content article').length===1"))
            js('window.confirm=()=>true');click('已归档')
            wait(lambda:js("document.querySelector('#content article .tag')?.textContent==='已归档'"))
            click('范围规则');wait(lambda:js("document.querySelector('#content .empty')!==null"))
            click('工作区与会话');wait(lambda:js("document.querySelector('#content').textContent.includes('尚无工作区客户端注册')"))
            assert get(f'http://127.0.0.1:{http}/api/health')['verified_deliveries']==0
            click('变更记录');wait(lambda:js("document.querySelector('#content').textContent.includes('task.status')"))
            screenshot=cdp('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
            Path(args.screenshot).write_bytes(base64.b64decode(screenshot['data']))
            assert not errors,errors
            print(json.dumps({'status':'passed','flows':['project_registration','task_creation','rule_creation','optimistic_edit','real_preview','preview_does_not_count','archive_deactivation','empty_workspace_without_mock','audit_display'],'javascript_errors':len(errors),'screenshot':args.screenshot}),flush=True)
            ws.close()
        except BaseException:
            log.flush();log.seek(0);print(log.read()[-2500:],file=sys.stderr);print(locals().get('errors',[]),file=sys.stderr);raise
        finally:
            for process in reversed(processes):
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            log.close()


if __name__=='__main__':main()
