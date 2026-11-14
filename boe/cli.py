"""boe command line: serve | stdio | status | stop | init-table."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from .engine import default_home
from .server import default_port


def _health(port: int, timeout: float = 1.0) -> Optional[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            d = json.loads(r.read())
            return d if d.get("name") == "blades-table" else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def ensure_daemon(port: int, wait: float = 25.0) -> None:
    """Make sure a daemon answers on `port`; spawn one detached if not."""
    if _health(port):
        return
    home = default_home()
    home.mkdir(parents=True, exist_ok=True)
    lock_path = home / "spawn.lock"
    with open(lock_path, "w") as lf:
        try:
            import fcntl
            fcntl.flock(lf, fcntl.LOCK_EX)
        except ImportError:  # non-posix
            pass
        if not _health(port):
            log = open(home / "daemon.log", "ab")
            env = dict(os.environ, BOE_PORT=str(port))
            subprocess.Popen([sys.executable, "-m", "boe", "serve", "--port", str(port)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, env=env,
                             close_fds=True)
        deadline = time.time() + wait
        while time.time() < deadline:
            if _health(port):
                return
            time.sleep(0.2)
    raise SystemExit(f"blades-table daemon did not become healthy on port {port}; see {home / 'daemon.log'}")


# ------------------------------------------------------------------ bridge
async def _run_bridge(port: int) -> None:
    import mcp_types as types
    from mcp import Client
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    url = f"http://127.0.0.1:{port}/mcp"
    stack = contextlib.AsyncExitStack()
    holder: dict = {}
    lock = asyncio.Lock()

    async def connect():
        if holder.get("stack"):
            with contextlib.suppress(Exception):
                await holder["stack"].aclose()
        await asyncio.to_thread(ensure_daemon, port)
        s = contextlib.AsyncExitStack()
        holder["client"] = await s.enter_async_context(Client(url))
        holder["stack"] = s

    async def upstream(op):
        """Run op(client); on a transport failure re-ensure the daemon, reconnect and retry once."""
        async with lock:
            try:
                return await op(holder["client"])
            except Exception as first:
                logging.getLogger("boe.bridge").warning("upstream call failed (%r); reconnecting", first)
                await connect()
                return await op(holder["client"])

    await connect()
    instructions = holder["client"].instructions

    async def list_tools(ctx, params):
        async def op(c):
            tools, cursor = [], None
            while True:
                r = await c.list_tools(cursor=cursor)
                tools += r.tools
                cursor = r.next_cursor
                if not cursor:
                    return tools
        return types.ListToolsResult(tools=await upstream(op))

    async def call_tool(ctx, params):
        try:
            return await upstream(lambda c: c.call_tool(params.name, params.arguments or {}))
        except Exception as e:
            return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(
                {"ok": False, "errors": [f"bridge to daemon failed: {e}"]}))], is_error=True)

    async def list_prompts(ctx, params):
        r = await upstream(lambda c: c.list_prompts())
        return types.ListPromptsResult(prompts=r.prompts)

    async def get_prompt(ctx, params):
        return await upstream(lambda c: c.get_prompt(params.name, params.arguments))

    async def list_resources(ctx, params):
        r = await upstream(lambda c: c.list_resources())
        return types.ListResourcesResult(resources=r.resources)

    async def read_resource(ctx, params):
        return await upstream(lambda c: c.read_resource(str(params.uri)))

    server = Server("blades-table", instructions=instructions, on_list_tools=list_tools, on_call_tool=call_tool,
                    on_list_prompts=list_prompts, on_get_prompt=get_prompt, on_list_resources=list_resources,
                    on_read_resource=read_resource)
    try:
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())
    finally:
        with contextlib.suppress(Exception):
            await holder["stack"].aclose()


def cmd_stdio(args) -> int:
    home = default_home()
    home.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[boe-bridge] %(message)s")
    fh = logging.FileHandler(home / "bridge.log")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logging.getLogger().addHandler(fh)
    asyncio.run(_run_bridge(args.port or default_port()))
    return 0


# ----------------------------------------------------------------- others
def cmd_serve(args) -> int:
    from .server import serve
    serve(host=args.host, port=args.port or default_port(), open_browser=args.open)
    return 0


def cmd_status(args) -> int:
    port = args.port or default_port()
    h = _health(port)
    if not h:
        print(json.dumps({"running": False, "port": port}))
        return 1
    print(json.dumps({"running": True, "port": port, "pid": h.get("pid"), "campaign": h.get("campaign"),
                      "ui": f"http://127.0.0.1:{port}/", "mcp": f"http://127.0.0.1:{port}/mcp"}))
    return 0


def cmd_stop(args) -> int:
    port = args.port or default_port()
    h = _health(port)
    if not h:
        print("not running")
        return 0
    pid = h.get("pid")
    if not pid:
        print("daemon did not report a pid; stop it manually")
        return 1
    os.kill(int(pid), signal.SIGTERM)
    for _ in range(50):
        if not _health(port, 0.3):
            print("stopped")
            return 0
        time.sleep(0.1)
    print("daemon still running after SIGTERM")
    return 1


CLAUDE_MD = """# Blades Table: you are the Architect

This folder is a play table for **Blades of Ether**, a solo campaign where you (Claude) are the Architect (game master)
and the human is the player. The `blades-table` MCP server (see `.mcp.json`) holds all game state, dice and rules.

## Do this first
1. Call the `session_begin` tool. It returns the GM guide, campaign recap, party sheets and open threads.
   If there is no campaign yet, talk with the player about the story they want and use `campaign_create`,
   `creation_options` and `character_create`.
2. Never roll dice or track HP, cooldowns, positions or BP in your head. Use the tools (`roll_check`, `combat_*`,
   `character_advance`, ...). Use `rules_lookup` when unsure.
3. Keep the table UI current: `scene_set` on scene changes, `journal_add` for important events.
4. End every play session with `session_end` (recap + Bond Points).

The player watches the table at http://127.0.0.1:{port}/ (start the daemon with `boe serve`; the stdio bridge
`boe stdio` starts it automatically). Secrets (check difficulties, enemy stat cards, gm notes) are never shown there.
"""


def cmd_init_table(args) -> int:
    d = Path(args.dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    port = args.port or default_port()
    mcp_json = {"mcpServers": {"blades-table": {"type": "http", "url": f"http://127.0.0.1:{port}/mcp"}}}
    for name, text in ((".mcp.json", json.dumps(mcp_json, indent=2) + "\n"),
                       ("CLAUDE.md", CLAUDE_MD.format(port=port))):
        p = d / name
        if p.exists() and not args.force:
            print(f"skip {p} (exists; use --force to overwrite)")
        else:
            p.write_text(text)
            print(f"wrote {p}")
    print(f"Start the daemon with: boe serve   (UI http://127.0.0.1:{port}/), then open Claude Code in {d}")
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="boe", description="Blades Table: virtual tabletop + MCP server")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the daemon (UI + MCP)")
    s.add_argument("--port", type=int)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--open", action="store_true", help="open the UI in a browser")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("stdio", help="MCP stdio bridge to the daemon (starts it if needed)")
    s.add_argument("--port", type=int)
    s.set_defaults(fn=cmd_stdio)
    for n, f, h in (("status", cmd_status, "show daemon status"), ("stop", cmd_stop, "stop the daemon")):
        s = sub.add_parser(n, help=h)
        s.add_argument("--port", type=int)
        s.set_defaults(fn=f)
    s = sub.add_parser("init-table", help="write .mcp.json and CLAUDE.md into a play folder")
    s.add_argument("dir")
    s.add_argument("--port", type=int)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init_table)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
