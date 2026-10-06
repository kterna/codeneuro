"""CodeNeuro Command Line Interface (CLI)."""

import argparse
import os
import sys
from pathlib import Path
import uvicorn

from codeneuro.api import create_app
from codeneuro.exporter import RuleExporter
from codeneuro.mcp_server import create_mcp_server
from codeneuro.models import RuleStatus
from codeneuro.storage import Storage


def main():
    parser = argparse.ArgumentParser(
        prog="codeneuro",
        description="CodeNeuro - Cognitive Context & Scoped Rules Engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. Serve command (WebUI + API)
    serve_parser = subparsers.add_parser("serve", help="Start the WebUI and API server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Binding host (default: 0.0.0.0)")
    serve_parser.add_argument("--port", type=int, default=8800, help="Port to listen on (default: 8800)")
    serve_parser.add_argument("--db", default="codeneuro.db", help="SQLite database path")

    # 2. MCP command (Stdio mode for agent clients)
    mcp_parser = subparsers.add_parser("mcp", help="Run MCP Server over stdio")
    mcp_parser.add_argument("--db", default="codeneuro.db", help="SQLite database path")

    # 3. Export command (Generate .cursor/rules or CLAUDE.md)
    export_parser = subparsers.add_parser("export", help="Export rules to static .cursor/rules/*.mdc or CLAUDE.md")
    export_parser.add_argument("--project-id", required=True, help="Target project id in CodeNeuro")
    export_parser.add_argument("--task-id", default=None, help="Optional active task ID filter")
    export_parser.add_argument("--format", choices=["cursor", "claude"], default="cursor", help="Export target format")
    export_parser.add_argument("--out", default=".", help="Target workspace root directory")
    export_parser.add_argument("--db", default="codeneuro.db", help="SQLite database path")

    args = parser.parse_args()

    if args.command == "serve":
        storage = Storage(args.db)
        app = create_app(storage=storage)
        print(f"🚀 CodeNeuro WebUI & API running at http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "mcp":
        import asyncio
        storage = Storage(args.db)
        server = create_mcp_server(storage)
        if hasattr(server, "run_stdio_async"):
            asyncio.run(server.run_stdio_async())
        else:
            server.run(transport="stdio")
    elif args.command == "export":
        storage = Storage(args.db)
        rules = storage.list_rules(project_id=args.project_id, status=RuleStatus.ACTIVE)
        out_root = Path(args.out).resolve()
        if args.format == "cursor":
            paths = RuleExporter.export_cursor_rules(rules, out_dir=out_root, active_task_id=args.task_id)
            print(f"✅ Successfully exported {len(paths)} Cursor MDC rules to {out_root / '.cursor/rules'}")
        elif args.format == "claude":
            dest = RuleExporter.export_claude_md(rules, out_file=out_root / "CLAUDE.md", active_task_id=args.task_id)
            print(f"✅ Successfully compiled {len(rules)} rules into {dest}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
