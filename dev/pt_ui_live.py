"""Live-update check: page open in headless Chrome (CDP), state mutated over MCP, DOM must change without reload."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from cdp import Page
from mcpc import connect, call

async def main():
    p = await Page.open("http://127.0.0.1:8792/")
    await asyncio.sleep(2.5)
    nav0 = await p.eval("performance.getEntriesByType('navigation').length + ':' + performance.now()")
    live0 = await p.eval("(document.body.innerText.match(/live|connected|offline|reconnect/i)||[''])[0]")
    print("indicator at load:", live0)
    async with connect() as (s, _):
        await call(s, "scene_set", title="LIVE-TEST Scene Title", location="Test Loft", description="mutated over MCP", present=["Kael Varrow"], mood="eerie")
        await call(s, "journal_add", text="LIVE-TEST journal entry")
        await call(s, "roll_check", char_id="kael-varrow", attribute="might", label="LIVE-TEST roll")
        await asyncio.sleep(2)
        txt = await p.eval("document.body.innerText")
        for needle in ("LIVE-TEST Scene Title", "LIVE-TEST journal entry", "LIVE-TEST roll"):
            print(f"{needle!r} appears without reload:", needle in txt)
        await call(s, "combat_adjust", ops=[{"op": "special_points", "team_id": "t_kael-varrow", "value": 3}])
        await asyncio.sleep(1.5)
        print("special gauge updated:", "3 / 18" in (await p.eval("document.body.innerText")).replace("\n", " ") or "3/18" in (await p.eval("document.body.innerText")))
        reloaded = await p.eval("performance.getEntriesByType('navigation').length")
        t1 = await p.eval("performance.now()")
        print("page not reloaded (performance.now monotonic since load):", float(t1) > float(nav0.split(':')[1]))
        await p.shot("/tmp/ui-live.png")
        # secrets must not reach the DOM
        full = await p.eval("document.documentElement.outerHTML")
        for secret in ("SECRET-TEXT-ALPHA", "SECRET-TEXT-BETA", "informs for the Cinder", "Smoke Bomb"):
            print(f"DOM contains {secret!r}:", secret in full)
        # end combat, then re-render out of combat
        await call(s, "combat_end", outcome="truce", summary="screenshot time")
        await asyncio.sleep(2)
        await p.shot("/tmp/ui-nocombat.png")
        print("after combat_end body mentions Yard fight map:", "YARD FIGHT" in (await p.eval("document.body.innerText")))
    print("console problems:", p.console_errors())
    await p.close()
asyncio.run(main())
