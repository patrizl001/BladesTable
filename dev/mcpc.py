"""Tiny MCP client helper for playtests (dev only)."""
import asyncio, json, os, contextlib
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("BOE_URL", "http://127.0.0.1:8792/mcp")

@contextlib.asynccontextmanager
async def connect(url=URL):
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            yield s, init

def text_of(res):
    return "".join(getattr(c, "text", "") for c in res.content)

async def call(s, _tool, /, **args):
    res = await s.call_tool(_tool, args)
    t = text_of(res)
    try:
        return json.loads(t), bool(res.is_error)
    except Exception:
        return {"_raw": t}, bool(res.is_error)
