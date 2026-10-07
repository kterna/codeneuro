"""JSON-lines relay from a Pi extension to the real CodeNeuro stdio MCP sidecar."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .codex_hooks import find_config


async def relay(workspace, config, *, server_command=None, server_args=None):
    command = server_command or sys.executable
    args = server_args if server_args is not None else ['-m', 'codeneuro.cli', 'mcp', '--config', str(config), '--workspace', str(workspace), '--debug']
    parameters = StdioServerParameters(command=command, args=args, cwd=str(workspace), env=dict(os.environ))
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            print(json.dumps({'ready': True, 'tools': [t.model_dump(mode='json', by_alias=True) for t in listed.tools]}), flush=True)
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line:
                    return
                request = {}
                try:
                    if len(line) > 2_000_000:
                        raise ValueError('Request too large')
                    request = json.loads(line)
                    if request.get('method') == 'close':
                        return
                    if request.get('method') != 'tools/call':
                        raise ValueError('Unknown relay request')
                    result = await session.call_tool(request['name'], request.get('arguments', {}))
                    response = {'id': request['id'], 'result': result.model_dump(mode='json', by_alias=True)}
                except Exception as exc:
                    response = {'id': request.get('id'), 'error': 'CodeNeuro MCP request failed: ' + type(exc).__name__}
                print(json.dumps(response, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    try:
        asyncio.run(relay(workspace, args.config or find_config(workspace)))
        return 0
    except Exception as exc:
        print(json.dumps({'ready': False, 'error': 'CodeNeuro MCP startup failed: ' + type(exc).__name__}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
