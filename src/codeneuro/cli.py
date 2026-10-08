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
                           ('close-session','Close an agent session'),('sync','Synchronize task-scoped static rules to a native worktree'),
                           ('evidence-export','Export receipt-backed experiment evidence'),
                           ('evidence-verify','Verify a portable experiment bundle')]:
        command=sub.add_parser(name,help=help_text)
        command.add_argument('--db',default=default_db)
        if name=='evidence-export':
            command.add_argument('--project-id',required=True)
            command.add_argument('--task-id')
            command.add_argument('--session-id')
            command.add_argument('--since')
            command.add_argument('--until')
            command.add_argument('--classification')
            command.add_argument('--private',action='store_true')
            command.add_argument('--out',required=True)
        if name=='evidence-verify':
            command.add_argument('--bundle',required=True)
        if name=='serve':
            command.add_argument('--host',default='127.0.0.1');command.add_argument('--port',type=int,default=8800)
        if name in ('mcp','sync'):
            command.add_argument('--config', help='Workstation .codeneuro.json for pinned remote Hub sidecar')
            command.add_argument('--workspace', help='Native Windows/Linux workspace path')
        if name=='sync':
            command.add_argument('--watch', action='store_true')
            command.add_argument('--format', choices=['cursor','claude','both'], default='both')
            command.add_argument('--interval', type=float, default=2)
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
    if args.command in ('evidence-export','evidence-verify'):
        from .evidence import EvidenceError, export_bundle, verify_bundle
        try:
            if args.command=='evidence-export':
                result=export_bundle(args.db,args.project_id,args.out,task_id=args.task_id,
                    session_id=args.session_id,since=args.since,until=args.until,
                    classification_path=args.classification,private=args.private)
            else:
                result=verify_bundle(args.bundle)
            print(json.dumps(result,ensure_ascii=False))
            return 0
        except (EvidenceError, OSError, sqlite3.Error, ValueError) as exc:
            print(json.dumps({'error':'evidence_error','detail':str(exc)},ensure_ascii=False),file=sys.stderr)
            return 2
    if args.command=='doctor':
        from pathlib import Path
        from .migrations import SCHEMA_VERSION
        with sqlite3.connect(Path(args.db).resolve().as_uri()+'?mode=ro',uri=True) as connection:
            integrity=connection.execute('PRAGMA integrity_check').fetchone()[0]
            foreign_keys=list(connection.execute('PRAGMA foreign_key_check'))
            version=connection.execute('PRAGMA user_version').fetchone()[0]
        print(json.dumps({'integrity':integrity,'foreign_key_errors':foreign_keys,'schema_version':version,'expected_schema_version':SCHEMA_VERSION}))
        return 0 if integrity=='ok' and not foreign_keys and version==SCHEMA_VERSION else 1
    if args.command in ('mcp','sync') and args.config:
        from pathlib import Path
        from .client import discover_config, RemoteClient
        from .client_mcp import create_client_mcp
        try:
            config=discover_config(config_path=args.config)
            workspace=Path(args.workspace) if args.workspace else Path(config['config_path']).parent
            with RemoteClient(config,workspace,debug=getattr(args,'debug',False),timeout=8 if args.command=='sync' else 130) as client:
                if args.command=='mcp':
                    server=create_client_mcp(client,debug_mode=args.debug)
                    if hasattr(server,'run_stdio_async'):asyncio.run(server.run_stdio_async())
                    else:server.run(transport='stdio')
                else:
                    import threading
                    import signal
                    from .sync import StaticSync
                    watcher=StaticSync(client,formats=args.format,poll_interval=args.interval,
                                       status_callback=lambda result:print(json.dumps(result,ensure_ascii=False),flush=True))
                    if args.watch:
                        stop=threading.Event()
                        def stop_watching(*_):stop.set()
                        for signame in ('SIGINT','SIGTERM'):
                            if hasattr(signal,signame):signal.signal(getattr(signal,signame),stop_watching)
                        watcher.watch(stop)
                    else:
                        result=watcher.sync_once()
                        if result.get('state')!='current':return 2
            return 0
        except DomainError as exc:
            print(json.dumps({'error':exc.code,'detail':str(exc)}),file=sys.stderr)
            return 2
    if args.command=='sync':
        parser.error('sync requires --config and a trusted remote Hub')
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
