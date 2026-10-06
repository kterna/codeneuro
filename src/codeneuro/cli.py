"""CodeNeuro Command Line Interface (CLI)."""

import argparse
import os
import sys
import uvicorn

from codeneuro.api import create_app
from codeneuro.mcp_server import create_mcp_server
from codeneuro.storage import Storage


def main():
    parser = argparse.ArgumentParser(
        prog="codeneuro",
        description="CodeNeuro - Cognitive Context & Scoped Rules Engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Serve command (WebUI + API)
    serve_parser = subparsers.add_parser("serve", help="Start the WebUI and API server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Binding host (default: 0.0.0.0)")
    serve_parser.add_argument("--port", type=int, default=8800, help="Port to listen on (default: 8800)")
    serve_parser.add_argument("--db", default="codeneuro.db", help="SQLite database path")

    # MCP command (Stdio mode for agent clients)
    mcp_parser = subparsers.add_parser("mcp", help="Run MCP Server over stdio")
    mcp_parser.add_argument("--db", default="codeneuro.db", help="SQLite database path")

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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
