"""CodeNeuro administration and agent context commands."""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
from .database import DomainError
from .service import ContextService
from .storage import Storage


def main():
    parser=argparse.ArgumentParser(prog='codeneuro',description='Scoped context for coding agents')
    sub=parser.add_subparsers(dest='command',required=True)
    default_db=os.getenv('CODENEURO_DB',os.getenv('CODETOKEN_DB','codeneuro.db'))
    for name,help_text in [('serve','Serve WebUI and HTTP API'),('mcp','Serve MCP over stdio'),
                           ('export','Export a managed static rule snapshot'),('doctor','Read-only database checks'),
                           ('session','Register a real workspace session'),('context','Resolve context for a session'),
                           ('close-session','Close an agent session')]:
        command=sub.add_parser(name,help=help_text)
        command.add_argument('--db',default=default_db)
        if name=='serve':
            command.add_argument('--host',default='127.0.0.1');command.add_argument('--port',type=int,default=8800)
        if name in ('mcp','serve','session'):command.add_argument('--debug',action='store_true')
        if name in ('session','export'):
            command.add_argument('--project-id',required=True);command.add_argument('--task-id')
        if name=='session':
            command.add_argument('--workspace',required=True);command.add_argument('--client',default='CLI')
        if name=='export':
            command.add_argument('--format',choices=['cursor','claude'],default='cursor');command.add_argument('--out',required=True)
        if name in ('context','close-session'):command.add_argument('--session-id',required=True)
        if name=='context':
            command.add_argument('--file',required=True);command.add_argument('--request-id');command.add_argument('--json',action='store_true');command.add_argument('--max-chars',type=int,default=24000)
    args=parser.parse_args()
    if args.command=='doctor':
        from pathlib import Path
        from .migrations import SCHEMA_VERSION
        with sqlite3.connect(Path(args.db).resolve().as_uri()+'?mode=ro',uri=True) as connection:
            integrity=connection.execute('PRAGMA integrity_check').fetchone()[0]
            foreign_keys=list(connection.execute('PRAGMA foreign_key_check'))
            version=connection.execute('PRAGMA user_version').fetchone()[0]
        print(json.dumps({'integrity':integrity,'foreign_key_errors':foreign_keys,'schema_version':version,'expected_schema_version':SCHEMA_VERSION}))
        return 0 if integrity=='ok' and not foreign_keys and version==SCHEMA_VERSION else 1
    storage=Storage(args.db)
    try:
        service=ContextService(storage)
        if args.command=='serve':
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(storage=storage),host=args.host,port=args.port)
        elif args.command=='mcp':
            from .mcp_server import create_mcp_server
            debug=args.debug or os.getenv('CODENEURO_DEBUG',os.getenv('CODETOKEN_DEBUG','0')).lower() in ('1','true')
            server=create_mcp_server(storage,debug_mode=debug)
            if hasattr(server,'run_stdio_async'):asyncio.run(server.run_stdio_async())
            else:server.run(transport='stdio')
        elif args.command=='session':
            print(json.dumps(service.start_session(args.project_id,args.workspace,args.task_id,args.client,args.debug)))
        elif args.command=='context':
            result=service.resolve(session_id=args.session_id,file_path=args.file,request_id=args.request_id,max_chars=args.max_chars)
            print(result.model_dump_json() if args.json else result.rendered_markdown)
        elif args.command=='close-session':
            print(json.dumps(service.close_session(args.session_id)))
        elif args.command=='export':
            from .exporter import RuleExporter
            with storage.transaction(write=False):
                storage.validate_scope(args.project_id,args.task_id)
                root=service._workspace(storage.get_project(args.project_id),args.out)
                rules=service.eligible_rules(args.project_id,args.task_id)
                if args.format=='cursor':result=RuleExporter.export_cursor_rules(rules,root,args.task_id)
                else:result=[RuleExporter.export_claude_md(rules,root/'CLAUDE.md',args.task_id)]
            print(json.dumps({'files':[str(p) for p in result]}))
        return 0
    except DomainError as exc:
        print(json.dumps({'error':exc.code,'detail':str(exc)}),file=sys.stderr)
        return 2
    finally:
        storage.close()


if __name__=='__main__':
    sys.exit(main())
