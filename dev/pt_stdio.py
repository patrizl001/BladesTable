"""stdio bridge end-to-end: daemon down (must auto-spawn) and daemon up. Uses its own port/home."""
import asyncio, json, os, subprocess, sys, time, urllib.request
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = os.environ.get("STDIO_PORT", "8795"); HOME = "/tmp/boe-stdio"
ENV = dict(os.environ, BOE_HOME=HOME, BOE_PORT=PORT)
def alive():
    try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1); return True
    except Exception: return False
async def one(label):
    params = StdioServerParameters(command=f"{ROOT}/boe.sh", args=["stdio"], env=ENV)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            tools = await s.list_tools()
            res = await s.call_tool("campaign_list", {})
            print(label, "instructions ok:", bool(init.instructions), "tools:", len(tools.tools), "campaign_list:", "".join(c.text for c in res.content)[:100])
            return len(tools.tools)
async def main():
    subprocess.run([f"{ROOT}/boe.sh", "stop"], env=ENV, capture_output=True); time.sleep(1)
    subprocess.run(["rm", "-rf", HOME])
    assert not alive(), "port should be free"
    n1 = await one("[daemon down -> auto-spawn]")
    print("daemon alive after bridge exit (detached):", alive())
    n2 = await one("[daemon up]")
    # two concurrent bridges
    a, b = await asyncio.gather(one("[bridge A]"), one("[bridge B]"))
    assert n1 == n2 == a == b and n1 > 30, (n1, n2, a, b)
    subprocess.run([f"{ROOT}/boe.sh", "stop"], env=ENV, capture_output=True)
    print("PASS")
asyncio.run(main())
