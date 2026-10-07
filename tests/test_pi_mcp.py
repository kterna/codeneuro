"""Pi's proxy speaks real stdio MCP; no host MCP support is assumed."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_stdio_relay_preserves_schema_results_and_errors(tmp_path):
    server = tmp_path/'fixture_mcp.py'
    server.write_text('''from mcp.server.mcpserver import MCPServer
mcp=MCPServer("protocol-fixture")
@mcp.tool()
def echo(message:str)->str:
    if message=="fail":raise ValueError("fixture error")
    return "ACTUAL_MCP_RESULT:"+message
mcp.run()
''')
    source = Path(__file__).resolve().parents[1]/'src'
    script = ('import asyncio;from pathlib import Path;from codeneuro.integrations.pi_mcp import relay;'
              f'asyncio.run(relay(Path({str(tmp_path)!r}),Path("unused"),server_command={sys.executable!r},server_args=[{str(server)!r}]))')
    request = '\n'.join(json.dumps(x) for x in [
        {'id': 1, 'method': 'tools/call', 'name': 'echo', 'arguments': {'message': 'hello'}},
        {'id': 2, 'method': 'tools/call', 'name': 'echo', 'arguments': {'message': 'fail'}},
        {'method': 'close'}]) + '\n'
    process = subprocess.run([sys.executable, '-c', script], input=request, capture_output=True, text=True,
                             env={**os.environ, 'PYTHONPATH': str(source)}, timeout=20)
    assert process.returncode == 0, process.stderr
    lines = [json.loads(line) for line in process.stdout.splitlines()]
    assert lines[0]['ready']
    assert lines[0]['tools'][0]['inputSchema']['properties']['message']['type'] == 'string'
    assert lines[1]['result']['content'][0]['text'] == 'ACTUAL_MCP_RESULT:hello'
    assert lines[1]['result']['isError'] is False
    assert lines[2]['result']['isError'] is True


def test_pi_extension_mcp_tool_errors_and_native_context_injection(tmp_path):
    # Exercise actual extension callbacks and registration in Node. This tests
    # event semantics; the separate subprocess test above verifies real MCP wire.
    module = Path(__file__).resolve().parents[1]/'src/codeneuro/integrations/pi_extension.mjs'
    script = tmp_path/'pi-probe.mjs'
    script.write_text('''import assert from 'node:assert/strict';
import extension from '''+json.dumps(module.as_uri())+''';
const handlers = new Map();
const pi = {on(name, fn){handlers.set(name,fn);},registerTool(){}};
extension(pi);
assert.deepEqual([...handlers.keys()],['session_start','tool_call','tool_result','session_shutdown']);
const ctx={cwd:process.cwd(),sessionManager:{getSessionId:()=> 'real-pi-session'}};
// MCP tools already inject their own context; native adapter must not recurse.
assert.equal(await handlers.get('tool_call')({toolName:'codeneuro_read',toolCallId:'a',input:{}},ctx),undefined);
assert.equal(await handlers.get('tool_result')({toolName:'codeneuro_read',toolCallId:'a',content:[]},ctx),undefined);
console.log('Pi extension event registration and recursion guard passed');
''')
    result = subprocess.run(['node', str(script)], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'passed' in result.stdout
