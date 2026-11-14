#!/usr/bin/env python3
"""Mock server for the Blades Table web UI (stdlib only).

Serves boe/web statically plus a fake copy of the real HTTP API (SPEC section 7):

  GET /api/state            player view from dev/mock_state.json
        ?combat=0           combat nulled out
        ?empty=1            "no campaign yet" response
        ?partial=1          strips lots of optional fields (robustness check)
        ?view=gm            adds a few fake GM-only extras
  GET /api/events           SSE: `event: state` now, on every mock-file change and every few seconds
  GET /api/health

Usage: python3 dev/mock_server.py [--port 8799] [--host 127.0.0.1] [--interval 6]
Edit dev/mock_state.json while it runs and the page updates live.
"""
import argparse
import copy
import json
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.normpath(os.path.join(HERE, "..", "boe", "web"))
MOCK = os.path.join(HERE, "mock_state.json")

_lock = threading.Lock()
_bump = 0
_last_mtime = 0.0
INTERVAL = 6.0


def mtime():
    try:
        return os.stat(MOCK).st_mtime
    except OSError:
        return 0.0


def current_version():
    with _lock:
        return _bump


def bump():
    global _bump
    with _lock:
        _bump += 1
        return _bump


def ticker():
    """Bump the version every INTERVAL seconds and whenever the mock file changes."""
    global _last_mtime
    _last_mtime = mtime()
    waited = 0.0
    while True:
        time.sleep(0.5)
        waited += 0.5
        m = mtime()
        if m != _last_mtime:
            _last_mtime = m
            waited = 0.0
            bump()
        elif waited >= INTERVAL:
            waited = 0.0
            bump()


def load_mock():
    with open(MOCK, "r", encoding="utf-8") as f:
        return json.load(f)


def gm_extras(st):
    """Fake the unredacted view: NPC hp, GM-only entity, notes."""
    st = copy.deepcopy(st)
    hp = {"c_g1": (6, 14), "c_r1": (9, 9), "c_vc": (11, 12), "c_cart": (4, 4)}
    cb = st.get("combat")
    if cb:
        for cid, c in cb.get("combatants", {}).items():
            if cid in hp:
                c["hp"], c["max_hp"] = hp[cid]
                c["card"] = {"role": c.get("role"), "attack": {"dis": 1, "normal": 2, "adv": 3},
                             "defense": {"dis": 0, "normal": 1, "adv": 2}, "hp": hp[cid][1], "movement": 3,
                             "initiative": 3, "affinities": ["wind"], "notes": "Mock card."}
    st.setdefault("entities", {})["e_secret"] = {
        "id": "e_secret", "kind": "secret", "name": "Who cut the Core's lamp-lines",
        "summary": "Vex Corrow was paid by someone inside the Skyfarer's Guild.", "details": "Reveal in arc 2.",
        "tags": ["twist"], "status": "hidden", "gm_only": True,
        "gm_notes": "The paymaster is Captain Haldane's brother.", "card": None, "updated_session": 3}
    if "e_vex" in st.get("entities", {}):
        st["entities"]["e_vex"]["gm_notes"] = "Vex secretly wants out of the Syndicate."
    st.setdefault("journal", []).append({"id": "jgm", "ts": "2026-11-09T19:23:00Z", "session": 3, "arc": 1,
                                         "kind": "note", "text": "GM: the Raptor is Vex's pet; it flees at half HP.",
                                         "tags": ["gm"], "gm_only": True})
    return st


def strip_partial(st):
    """Remove lots of optional data to prove the UI never throws on absent fields."""
    st = copy.deepcopy(st)
    for k in ("meta", "clock", "scene", "affinity", "teams", "sessions", "arcs"):
        st.pop(k, None)
    for c in st.get("characters", {}).values():
        for k in ("derived", "bonds", "talents", "arc_abilities", "bp", "inventory", "pronouns", "attributes"):
            c.pop(k, None)
        for a in c.get("arts", []):
            a.pop("tags", None)
    cb = st.get("combat")
    if cb:
        cb.pop("special", None)
        cb.pop("order", None)
        cb["map"].pop("cells", None)
        cb["map"].pop("height", None)
        for c in cb["combatants"].values():
            c.pop("statuses", None)
            c.pop("facing", None)
            c.pop("cooldowns", None)
        first = next(iter(cb["combatants"].values()))
        first["pos"] = None
    for e in st.get("entities", {}).values():
        e.pop("summary", None)
        e.pop("status", None)
    for r in st.get("rolls", []):
        r.pop("mods", None)
        r.pop("tier", None)
        r.pop("dice", None)
    st["journal"] = [{"text": "Entry with almost nothing in it"}, {}]
    return st


def build_state(query):
    version = current_version()
    if query.get("empty", ["0"])[0] not in ("0", ""):
        return {"ok": True, "version": version, "has_campaign": False}
    st = load_mock()
    st["version"] = version + int(st.get("version", 0))
    if query.get("combat", ["1"])[0] == "0":
        st["combat"] = None
    if query.get("partial", ["0"])[0] not in ("0", ""):
        st = strip_partial(st)
    if query.get("view", ["player"])[0] == "gm":
        st = gm_extras(st)
        st["view"] = "gm"
    return st


class Handler(SimpleHTTPRequestHandler):
    server_version = "BladesTableMock/1"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, fmt, *args):
        if "/api/events" in (args[0] if args else ""):
            return
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/health":
            return self._json({"ok": True, "name": "blades-table", "version": current_version()})
        if u.path == "/api/state":
            try:
                return self._json(build_state(q))
            except Exception as e:  # keep the mock alive on a bad edit of the JSON
                return self._json({"ok": False, "error": "mock_state.json: %s" % e}, 500)
        if u.path == "/api/events":
            return self._sse()
        if u.path == "/api/campaigns":
            return self._json({"ok": True, "campaigns": [{"slug": "the-lantern-road", "name": "The Lantern Road"}]})
        if u.path.startswith("/api/"):
            return self._json({"ok": False, "error": "not found"}, 404)
        return super().do_GET()

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last = None
        beat = time.time()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            while True:
                v = current_version()
                if v != last:
                    last = v
                    self.wfile.write(("event: state\ndata: %s\n\n" % json.dumps({"version": v})).encode())
                    self.wfile.flush()
                if time.time() - beat > 15:
                    beat = time.time()
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                time.sleep(0.4)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


def main():
    global INTERVAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--interval", type=float, default=6.0, help="seconds between automatic version bumps")
    args = ap.parse_args()
    INTERVAL = args.interval
    threading.Thread(target=ticker, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print("mock table on http://%s:%d/  (serving %s)" % (args.host, args.port, WEB), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
