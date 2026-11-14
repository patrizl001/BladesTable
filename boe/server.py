"""ASGI app: MCP streamable HTTP at /mcp + player-view HTTP API + SSE + static web UI."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

from . import __version__, views
from . import tools_core
from .engine import Engine

WEB_DIR = Path(__file__).parent / "web"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}

PLACEHOLDER = """<!doctype html><meta charset=utf-8><title>Blades Table</title>
<body style="font-family:sans-serif;max-width:40em;margin:3em auto"><h1>Blades Table</h1>
<p>The web UI has not been built yet (boe/web is empty). The server is running: <code>/api/state</code>,
<code>/api/events</code> and <code>/mcp</code> work.</p>"""


def default_port() -> int:
    return int(os.environ.get("BOE_PORT", "8765"))


def build_mcp(engine: Engine) -> MCPServer:
    mcp = MCPServer("blades-table", instructions=tools_core.SERVER_INSTRUCTIONS, version=__version__)
    safe = tools_core.as_safe(mcp)
    tools_core.register(safe, engine)
    try:
        from . import tools_combat
    except ImportError as e:
        print(f"[boe] warning: combat tools not available ({e}); running without combat", file=sys.stderr)
    else:
        tools_combat.register(safe, engine)
    return mcp


def _host_ok(host_header: Optional[str]) -> bool:
    if not host_header:
        return False
    h = host_header.strip().lower()
    if h.startswith("["):
        h = h.split("]")[0] + "]"
    else:
        h = h.split(":")[0]
    return h in LOCAL_HOSTS


def build_app(engine: Engine, allow_any_host: bool = False) -> Starlette:
    mcp = build_mcp(engine)
    sec = TransportSecuritySettings(
        enable_dns_rebinding_protection=not allow_any_host,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "127.0.0.1", "localhost", "[::1]"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
                         "http://127.0.0.1", "http://localhost"],
    )
    # Build the SDK's own app only to initialise its session manager; we mount the ASGI endpoint ourselves.
    mcp.streamable_http_app(stateless_http=True, transport_security=sec)
    manager = mcp.session_manager
    mcp_asgi = StreamableHTTPASGIApp(manager)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    def guard(request: Request) -> Optional[PlainTextResponse]:
        if not allow_any_host and not _host_ok(request.headers.get("host")):
            return PlainTextResponse("invalid Host header", status_code=421)
        return None

    async def health(request: Request):
        if (g := guard(request)):
            return g
        return JSONResponse({"ok": True, "name": "blades-table", "version": engine.version,
                             "app_version": __version__, "pid": os.getpid(),
                             "campaign": engine.state["meta"]["slug"] if engine.state else None})

    async def api_state(request: Request):
        if (g := guard(request)):
            return g
        if request.query_params.get("view") == "gm":
            body = {"ok": True, "version": engine.version, "has_campaign": engine.state is not None,
                    "state": engine.state}
            return JSONResponse(body, headers={"Cache-Control": "no-store"})
        with engine._lock:
            body = views.player_view(engine.state, engine.version, engine.list_campaigns())
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    async def api_campaigns(request: Request):
        if (g := guard(request)):
            return g
        return JSONResponse({"ok": True, "campaigns": engine.list_campaigns()})

    async def api_events(request: Request):
        if (g := guard(request)):
            return g
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def cb(payload: dict):
            loop.call_soon_threadsafe(q.put_nowait, payload)

        engine.subscribe(cb)

        async def gen():
            try:
                yield "retry: 2000\n\n"
                first = {"version": engine.version, "epoch": engine.epoch,
                         "slug": engine.state["meta"]["slug"] if engine.state else None}
                yield f"event: state\ndata: {json.dumps(first)}\n\n"
                while True:
                    try:
                        p = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    while not q.empty():
                        p = q.get_nowait()
                    yield f"event: state\ndata: {json.dumps(p)}\n\n"
            finally:
                engine.unsubscribe(cb)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def static(request: Request):
        if (g := guard(request)):
            return g
        rel = request.path_params.get("path", "") or "index.html"
        root = WEB_DIR.resolve()
        target = (root / rel).resolve()
        if root not in target.parents and target != root:
            return PlainTextResponse("not found", status_code=404)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            if rel == "index.html":
                return HTMLResponse(PLACEHOLDER)
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(target, headers={"Cache-Control": "no-cache"})

    routes = [
        Route("/mcp", endpoint=mcp_asgi),
        Route("/mcp/", endpoint=mcp_asgi),
        Route("/api/health", health),
        Route("/api/state", api_state),
        Route("/api/events", api_events),
        Route("/api/campaigns", api_campaigns),
        Route("/", static),
        Route("/{path:path}", static),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.engine = engine
    app.state.mcp = mcp
    return app


def serve(host: str = "127.0.0.1", port: Optional[int] = None, open_browser: bool = False,
          engine: Optional[Engine] = None) -> None:
    import uvicorn

    port = port or default_port()
    os.environ["BOE_PORT"] = str(port)
    engine = engine or Engine()
    engine.ui_url = f"http://127.0.0.1:{port}/"
    app = build_app(engine, allow_any_host=host not in ("127.0.0.1", "localhost", "::1"))
    pidfile = engine.home / "daemon.pid"
    pidfile.write_text(str(os.getpid()))
    if open_browser:
        import threading
        import webbrowser

        def _open():
            import shutil
            import subprocess
            import time
            time.sleep(1.0)
            if shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", engine.ui_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                webbrowser.open(engine.ui_url)
        threading.Thread(target=_open, daemon=True).start()
    print(f"[boe] Blades Table on http://{host}:{port}/  (MCP at /mcp, data in {engine.home})", file=sys.stderr)
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning", timeout_graceful_shutdown=2)
    finally:
        with contextlib.suppress(OSError):
            if pidfile.exists() and pidfile.read_text().strip() == str(os.getpid()):
                pidfile.unlink()
