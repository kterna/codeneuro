"""Isolated Chromium acceptance of the rebuilt Web intake/archive/ledger flow.

Creates a temporary NEW-schema database and browser profile; never visits the
another service, opens production data or writes to a user browser profile.
"""
import argparse
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


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def wait(check, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(.1)
    raise TimeoutError('Browser acceptance condition not reached.')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--chromium', required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='codeneuro-browser-') as temporary:
        temp = Path(temporary)
        database = temp / 'new.db'
        repo_env = {**os.environ, 'PYTHONPATH': str(root / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
        subprocess.run([sys.executable, '-B', '-m', 'codeneuro', 'migrate',
                        '--db', str(database)], cwd=root, env=repo_env, check=True)
        env = repo_env
        http_port, debug_port = free_port(), free_port()
        processes = []
        log = (temp / 'browser.log').open('w+')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def fetch(url):
            with opener.open(url, timeout=2) as response:
                return json.load(response)
        try:
            processes.append(subprocess.Popen([sys.executable, '-B', '-m', 'codeneuro',
                'serve', '--db', str(database), '--port', str(http_port)], cwd=root,
                env=env, stdout=log, stderr=log))
            def ready():
                with opener.open(f'http://127.0.0.1:{http_port}/api/projects', timeout=2) as response:
                    return json.load(response) == []
            wait(ready)
            processes.append(subprocess.Popen([args.chromium, '--headless', '--no-sandbox',
                '--disable-gpu', '--disable-background-networking', '--disable-component-update',
                '--disable-sync', '--no-first-run', '--password-store=basic',
                f'--user-data-dir={temp / "profile"}', f'--remote-debugging-port={debug_port}',
                'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            targets = wait(lambda: fetch(f'http://127.0.0.1:{debug_port}/json/list'))
            page = next(item for item in targets if item.get('type') == 'page')
            with connect(page['webSocketDebuggerUrl'], max_size=None, legacy=True) as websocket:
                serial = 0
                errors = []
                def cdp(method, params=None):
                    nonlocal serial
                    serial += 1
                    websocket.send(json.dumps({'id': serial, 'method': method, 'params': params or {}}))
                    while True:
                        response = json.loads(websocket.recv(timeout=15))
                        if response.get('method') == 'Runtime.exceptionThrown':
                            errors.append(response['params'])
                        if response.get('id') == serial:
                            if 'error' in response:
                                raise RuntimeError(response['error'])
                            return response.get('result', {})
                def js(source):
                    reply = cdp('Runtime.evaluate', {'expression': source,
                        'returnByValue': True, 'awaitPromise': True})
                    if 'exceptionDetails' in reply:
                        raise RuntimeError(reply['exceptionDetails'])
                    return reply.get('result', {}).get('value')
                def fill(selector, value):
                    js(f"(()=>{{let field=document.querySelector({json.dumps(selector)});"
                       f"field.value={json.dumps(value)};field.dispatchEvent(new Event('input',{{bubbles:true}}))}})()")
                def click(label):
                    wait(lambda: js(f"[...document.querySelectorAll('button')].some(b=>b.textContent.trim().endsWith({json.dumps(label)})&&!b.disabled)"))
                    js(f"[...document.querySelectorAll('button')].find(b=>b.textContent.trim().endsWith({json.dumps(label)})).click()")
                cdp('Runtime.enable'); cdp('Page.enable')
                cdp('Page.navigate', {'url': f'http://127.0.0.1:{http_port}/app/'})
                wait(lambda: js("!!document.querySelector('.sidebar') && document.querySelector('#health').textContent.includes('已连接')"))
                assert not js("!!document.querySelector('#hub-token')")
                assert js("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") == '#a49aff'
                assert js("getComputedStyle(document.querySelector('.sidebar')).position") == 'fixed'
                click('注册项目')
                wait(lambda: js("document.querySelector('#editor').open"))
                fill('#new-project-id', 'browser-project')
                fill('#new-project-name', 'Browser test')
                click('保存')
                wait(lambda: js("document.querySelector('#project').value === 'browser-project'"))
                click('需求与任务看板')
                wait(lambda: js("!!document.querySelector('#demand-text')"))
                fill('#demand-text', '新增退款流程并确保幂等。')
                click('提交原文需求')
                wait(lambda: js("document.body.innerText.includes('新增退款流程并确保幂等。')"))
                assert js("document.querySelectorAll('.original-text').length") == 1
                click('确认归档')
                wait(lambda: js("document.querySelector('#editor').open"))
                fill('#editor textarea', 'Coding Agent confirmed completion.')
                click('保存')
                wait(lambda: js("document.body.innerText.includes('完成摘要：Coding Agent confirmed completion.')"))
                wait(lambda: js("[...document.querySelectorAll('.tag')].some(x=>x.textContent.includes('archived'))"))
                assert not errors, errors
                print(json.dumps({'result': 'passed', 'flow': 'intake_archival_ledger',
                                  'javascript_errors': len(errors)}))
                try:
                    cdp('Browser.close')
                except (OSError, RuntimeError):
                    pass  # Browser.close can end the CDP connection before acknowledging.
        except BaseException:
            log.flush();log.seek(0)
            print(log.read()[-3000:], file=sys.stderr)
            raise
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
            log.close()
            time.sleep(0.5)



if __name__ == '__main__':
    main()
