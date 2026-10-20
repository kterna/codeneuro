"""Isolated Chromium acceptance of the Requirement/Task and Topic workbench.

Only a new temporary database, loopback service and disposable browser profile are
used. The script never connects to an existing service or normal browser profile.
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

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from browser_topics import run_topics_flow
from browser_tasks import run_task_flow


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


class Page:
    def __init__(self, websocket):
        self.websocket = websocket
        self.serial = 0
        self.errors = []

    def cdp(self, method, params=None):
        self.serial += 1
        self.websocket.send(json.dumps({'id': self.serial, 'method': method, 'params': params or {}}))
        while True:
            response = json.loads(self.websocket.recv(timeout=15))
            if response.get('method') == 'Runtime.exceptionThrown':
                self.errors.append(response['params'])
            if response.get('id') == self.serial:
                if 'error' in response:
                    raise RuntimeError(response['error'])
                return response.get('result', {})

    def js(self, source):
        reply = self.cdp('Runtime.evaluate', {'expression': source, 'returnByValue': True, 'awaitPromise': True})
        if 'exceptionDetails' in reply:
            raise RuntimeError(reply['exceptionDetails'])
        return reply.get('result', {}).get('value')

    def until(self, expression):
        try:
            return wait(lambda: self.js(expression))
        except TimeoutError:
            raise TimeoutError('Browser condition: ' + expression) from None

    def fill(self, selector, value):
        self.js(f"(()=>{{const f=document.querySelector({json.dumps(selector)});"
                f"if(!f||f.disabled||f.readOnly)throw Error('Field unavailable: '+{json.dumps(selector)});"
                f"f.value={json.dumps(value)};f.dispatchEvent(new Event('input',{{bubbles:true}}));"
                "f.dispatchEvent(new Event('change',{bubbles:true}));})()")

    def field(self, label, value, scope):
        self.js(f"(()=>{{const l=[...document.querySelectorAll({json.dumps(scope + ' label')})]"
                f".find(l=>l.textContent.trim().startsWith({json.dumps(label)}));"
                "const f=l?.querySelector('input,textarea,select');"
                f"if(!f||f.disabled||f.readOnly)throw Error('Field unavailable: '+{json.dumps(label)});"
                f"f.value={json.dumps(value)};f.dispatchEvent(new Event('input',{{bubbles:true}}));"
                "f.dispatchEvent(new Event('change',{bubbles:true}));})()")

    def click(self, label, scope=''):
        expression = (f"[...document.querySelectorAll({json.dumps((scope + ' button').strip())})]"
                      f".find(b=>b.textContent.trim().endsWith({json.dumps(label)})&&!b.disabled&&b.getClientRects().length)")
        self.until('!!(' + expression + ')')
        self.js(f"(()=>{{const b={expression};b.scrollIntoView({{block:'center'}});b.click()}})()")


def stop(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        # Only this script's owned process tree; never kill browsers by executable name.
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--chromium', required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    with tempfile.TemporaryDirectory(prefix='codeneuro-browser-') as temporary:
        temp = Path(temporary)
        database = temp / 'new.db'
        env = {**os.environ, 'PYTHONPATH': str(root / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
        subprocess.run([sys.executable, '-B', '-m', 'codeneuro', 'init-db', '--db', str(database)],
                       cwd=root, env=env, check=True)
        http_port, debug_port = free_port(), free_port()
        base_url = f'http://127.0.0.1:{http_port}'
        processes = []
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def fetch(url):
            with opener.open(url, timeout=2) as response:
                return json.load(response)
        with (temp / 'browser.log').open('w+') as log:
            try:
                processes.append(subprocess.Popen([sys.executable, '-B', '-m', 'codeneuro',
                    'serve', '--db', str(database), '--port', str(http_port)],
                    cwd=root, env=env, stdout=log, stderr=log))
                wait(lambda: fetch(base_url + '/api/projects') == [])
                browser = subprocess.Popen([args.chromium, '--headless', '--no-sandbox',
                    '--disable-gpu', '--disable-background-networking', '--disable-component-update',
                    '--disable-sync', '--no-first-run', '--password-store=basic',
                    f'--user-data-dir={temp / "profile"}', f'--remote-debugging-port={debug_port}',
                    'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                processes.append(browser)
                targets = wait(lambda: fetch(f'http://127.0.0.1:{debug_port}/json/list'))
                target = next(item for item in targets if item.get('type') == 'page')
                with connect(target['webSocketDebuggerUrl'], max_size=2**22, legacy=True) as websocket:
                    page = Page(websocket)
                    try:
                        page.cdp('Runtime.enable')
                        page.cdp('Page.enable')
                        page.cdp('Emulation.setDeviceMetricsOverride', {
                            'width': 1280, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
                        page.cdp('Page.navigate', {'url': base_url + '/app/'})
                        page.until("!!document.querySelector('.sidebar') && document.querySelector('#health')?.classList.contains('connected')")
                        assert not page.js("!!document.querySelector('#hub-token')")
                        page.js("document.querySelector('#new-project').click()")
                        page.until("document.querySelector('#editor').open")
                        page.fill('#new-project-id', 'browser-project')
                        page.fill('#new-project-name', 'Browser test')
                        page.click('保存', '#editor')
                        page.until("document.querySelector('#project').value === 'browser-project'")
                        task_checks = run_task_flow(page, fetch, base_url, wait)
                        topic_checks = run_topics_flow(database, page, fetch, base_url, wait)
                        assert not page.errors, page.errors
                        result = {'result': 'passed', 'flows': [*task_checks, *topic_checks],
                                  'javascript_errors': len(page.errors)}
                    except BaseException:
                        print(json.dumps({'browser_failure': page.js('document.body.innerText.slice(0,2400)'),
                                          'javascript_errors': page.errors}, ensure_ascii=False), file=sys.stderr)
                        raise
                    finally:
                        try:
                            page.cdp('Browser.close')
                        except (ConnectionClosed, OSError, RuntimeError):
                            pass
                try:
                    browser.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stop(browser)
            except BaseException:
                log.flush()
                log.seek(0)
                print(log.read()[-3000:], file=sys.stderr)
                raise
            finally:
                for process in reversed(processes):
                    stop(process)
    # Only report success after browser/service/profile/log cleanup has completed.
    print(json.dumps({**result, 'temporary_environment_removed': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
