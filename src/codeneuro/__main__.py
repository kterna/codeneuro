"""CodeNeuro CLI: explicit schema initialization and MCP/HTTP Hub."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from .adapters.mcp.tools import create_mcp
from .adapters.sqlite.uow import SqliteUnitOfWork
from .workflows.product import Product


def create_http_app(product: Product):
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    mcp = create_mcp(product)
    transport = mcp.streamable_http_app(streamable_http_path='/',
        json_response=True, stateless_http=True, host='0.0.0.0')

    @asynccontextmanager
    async def lifespan(app):
        async with transport.router.lifespan_context(transport):
            yield

    from .adapters.http.api import create_router
    app = FastAPI(lifespan=lifespan)
    app.include_router(create_router(product))
    app.mount('/mcp', transport)
    static = Path(__file__).resolve().parent / 'static'
    if (static / 'index.html').is_file():
        app.mount('/app/assets', StaticFiles(directory=str(static / 'assets')), name='workbench-assets')

        @app.get('/app/')
        def workbench():
            return FileResponse(static / 'index.html')

        @app.get('/')
        def home():
            return RedirectResponse('/app/')
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(prog='codeneuro')
    parser.add_argument('mode', choices=('migrate', 'mcp', 'serve'))
    parser.add_argument('--db', required=True, help='Explicitly migrated CodeNeuro database')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8801)
    args = parser.parse_args(argv)
    if args.mode == 'migrate':
        from alembic import command
        from alembic.config import Config
        config = Config()
        config.set_main_option('script_location', str(Path(__file__).resolve().parent / 'migrations'))
        config.set_main_option('codeneuro_db', args.db)
        command.upgrade(config, 'head')
        return
    uow = SqliteUnitOfWork(args.db)
    try:
        product = Product(uow)
        if args.mode == 'mcp':
            server = create_mcp(product)
            asyncio.run(server.run_stdio_async())
        else:
            import uvicorn
            if args.host not in ('127.0.0.1', 'localhost', '::1'):
                print('Warning: HTTP API and MCP have no authentication; bind only on a trusted network.', flush=True)
            uvicorn.run(create_http_app(product), host=args.host, port=args.port)
    finally:
        uow.dispose()


if __name__ == '__main__':
    main()
