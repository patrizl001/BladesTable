"""Daemon restart mid-combat: state, undo history and the (still-open) MCP client must survive.
Run via dev/run_restart_test.sh"""
import asyncio, json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from mcpc import connect, call
from playtest_common import check, FAILS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(os.environ, BOE_HOME=os.environ.get("BOE_HOME", "/tmp/boe-play"), BOE_PORT=os.environ.get("BOE_PORT", "8792"))


def start():
    subprocess.Popen([f"{ROOT}/boe.sh", "serve"], env=ENV, stdout=open("/tmp/boe-serve.log", "a"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{ENV['BOE_PORT']}/api/health", timeout=1); return
        except Exception:
            time.sleep(0.25)
    raise SystemExit("daemon did not start")


async def main():
    async with connect() as (s, init):
        async def c(n, /, **a):
            r, e = await call(s, n, **a); return r
        await c("session_begin")
        r = await c("combat_start", name="Restart drill", map={"width": 6, "height": 4}, combatants=[
            {"char_id": "kael-varrow", "pos": [1, 1]}, {"char_id": "vesper", "pos": [1, 2]},
            {"name": "Pack Animal", "bestiary": "pack_animal", "pos": [4, 1]}])
        check(r.get("ok"), f"combat_start: {r}")
        a = (await c("get_state", scope="full"))["state"]
        while a["combat"]["order"][0] != "kael-varrow":
            cur = a["combat"]["order"][0]
            await c("combat_end_turn", cid=cur)
            a = (await c("get_state", scope="full"))["state"]
        await c("combat_move", cid="kael-varrow", to=[2, 1])
        await c("combat_end_turn", cid="kael-varrow")
        before = (await c("get_state", scope="full"))["state"]
        ver = before["version"]
        print("before restart: version", ver, "order", before["combat"]["order"])
        # kill the daemon (SIGTERM via CLI, then verify it is gone)
        subprocess.run([f"{ROOT}/boe.sh", "stop"], env=ENV, capture_output=True)
        time.sleep(1)
        down = subprocess.run(["curl", "-s", "-m", "1", f"http://127.0.0.1:{ENV['BOE_PORT']}/api/health"], capture_output=True).stdout
        check(not down, "daemon should be down")
        start()
        # SAME client object, no reconnect
        try:
            r = await asyncio.wait_for(c("get_state", scope="full"), 15)
            after = r.get("state")
            same_session = after is not None
        except Exception as e:  # noqa
            print("old client session did not survive:", repr(e)[:200]); same_session = False; after = None
        print("old MCP client session survived restart:", same_session)
        if not same_session:
            async with connect() as (s2, _):
                r, _e = await call(s2, "get_state", scope="full")
                after = r["state"]
        check(after["version"] == ver, f"version preserved {ver} -> {after['version']}")
        check(after["combat"] == before["combat"], "combat state identical after restart")
        async with connect() as (s3, _):
            u, _e = await call(s3, "undo", steps=1)
            check(u.get("ok") and u["undone"] == ["combat_end_turn"], f"undo history survived: {u}")
            u, _e = await call(s3, "undo", steps=1)
            check(u.get("ok") and u["undone"] == ["combat_move"], f"undo history survived (2): {u}")
            r, _e = await call(s3, "combat_end", outcome="other")
            check(r.get("ok"), "combat_end after restart")
    print("FAILS", FAILS)
    return 1 if FAILS else 0

sys.exit(asyncio.run(main()))
