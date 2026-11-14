"""Shared helpers for playtest scripts."""
import json, os
from mcpc import call

VERBOSE = os.environ.get("PT_VERBOSE", "1") == "1"
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  ASSERT FAIL:", msg)
    return cond


def friction(msg):
    print("  FRICTION:", msg)


class Table:
    def __init__(self, s):
        self.s = s
        self.calls = 0

    async def __call__(self, tool, /, lim=700, quiet=False, **a):
        r, err = await call(self.s, tool, **a)
        self.calls += 1
        txt = json.dumps(r, ensure_ascii=False)
        if VERBOSE and not quiet:
            print(f">>> {tool} {json.dumps(a, ensure_ascii=False)[:220]}\n<<< {'ERR ' if err else ''}{txt[:lim]}{'...[%d]' % len(txt) if len(txt) > lim else ''}")
        check("Traceback" not in txt and "Internal error" not in txt and "Error executing tool" not in txt,
              f"{tool}: unhandled exception text: {txt[:200]}")
        return r


def pick(d, *path, default=None):
    for p in path:
        if isinstance(d, dict):
            d = d.get(p)
        elif isinstance(d, list) and isinstance(p, int) and -len(d) <= p < len(d):
            d = d[p]
        else:
            return default
    return d if d is not None else default


