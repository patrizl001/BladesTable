"""Minimal Chrome DevTools helper for UI checks (dev only; needs `websockets`, not a runtime dep)."""
import asyncio, base64, json, urllib.request
import websockets

class Page:
    def __init__(self, ws): self.ws, self.id, self.events, self.waiters = ws, 0, [], {}
    @classmethod
    async def open(cls, url, port=9333, w=1600, h=1000):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
        tgt = json.load(urllib.request.urlopen(req))
        ws = await websockets.connect(tgt["webSocketDebuggerUrl"], max_size=50_000_000)
        p = cls(ws); p.target = tgt["id"]; p.port = port
        asyncio.create_task(p._reader())
        for m in ("Page.enable", "Runtime.enable", "Log.enable", "Network.enable"):
            await p.send(m)
        await p.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
        await p.send("Page.navigate", url=url)
        return p
    async def _reader(self):
        async for m in self.ws:
            d = json.loads(m)
            if "id" in d and d["id"] in self.waiters: self.waiters.pop(d["id"]).set_result(d)
            else: self.events.append(d)
    async def send(self, method, **params):
        self.id += 1; fut = asyncio.get_event_loop().create_future(); self.waiters[self.id] = fut
        await self.ws.send(json.dumps({"id": self.id, "method": method, "params": params}))
        return (await asyncio.wait_for(fut, 30)).get("result", {})
    async def eval(self, js):
        r = await self.send("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")
    async def shot(self, path):
        r = await self.send("Page.captureScreenshot", format="png")
        open(path, "wb").write(base64.b64decode(r["data"]))
    def console_errors(self):
        out = []
        for e in self.events:
            if e.get("method") == "Runtime.exceptionThrown":
                out.append("EXC " + json.dumps(e["params"]["exceptionDetails"])[:300])
            elif e.get("method") == "Runtime.consoleAPICalled" and e["params"]["type"] in ("error", "warning"):
                out.append(e["params"]["type"] + " " + " ".join(str(a.get("value", a.get("description", ""))) for a in e["params"]["args"])[:300])
            elif e.get("method") == "Log.entryAdded" and e["params"]["entry"]["level"] in ("error", "warning"):
                out.append("LOG " + e["params"]["entry"]["level"] + " " + e["params"]["entry"]["text"][:200] + " " + e["params"]["entry"].get("url", ""))
        return out
    async def close(self):
        await self.ws.close()
        try: urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/close/{self.target}")
        except Exception: pass
