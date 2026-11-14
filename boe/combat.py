"""Blades Table combat logic: pure functions `fn(engine, ...) -> dict` (no MCP here).

Conventions: positions [x, y], origin top-left, facing N = up (y-1). Turn order shifts: delta > 0 acts
SOONER, delta < 0 acts LATER. Every action runs inside `engine.txn`, so a GameError rolls everything back.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Optional

try:
    from .engine import GameError
except Exception:  # pragma: no cover
    class GameError(Exception):
        """User-facing rule/usage error."""

try:
    from .dice import count_successes, tier as _tier
except Exception:  # pragma: no cover
    def count_successes(dice):
        return sum(1 for d in dice if d >= 5)

    def _tier(net):
        return "success" if net >= 2 else "near_hit" if net == 1 else "near_miss" if net == 0 else "failure"

IDEAS = {"bravery": ["might", "willpower", "calculation"], "truth": ["gut", "experience", "knowledge"],
         "compassion": ["stamina", "empathy", "attunement"],
         "justice": ["swiftness", "improvisation", "passion"]}
ELEMENT_IDEA = {"fire": "bravery", "water": "bravery", "wind": "truth", "ice": "truth",
                "earth": "compassion", "electricity": "compassion", "light": "justice", "dark": "justice"}
UNIQUE_EFFECTS = {"burning_blade": "fire", "arts_seal": "water", "blustering_gale": "wind",
                  "freezing_force": "ice", "cradling_earth": "earth", "electrifying_burst": "electricity",
                  "blade_of_light": "light", "shadow_manipulation": "dark"}
SHARED_EFFECTS = {"invigorating_steam": "bravery", "bitter_snowstorm": "truth",
                  "counter_spike": "compassion", "blinding_eclipse": "justice"}
ALL_EFFECTS = {**UNIQUE_EFFECTS, **SHARED_EFFECTS}

DIRS = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
ARROW = {"N": "^", "E": ">", "S": "v", "W": "<"}
CELL_DEFAULTS = {"wall": (True, True), "obstacle": (True, False), "cover": (True, False),
                 "hazard": (False, False), "difficult": (False, False), "feature": (False, False)}
GLYPH = {"wall": "#", "obstacle": "O", "cover": "=", "hazard": "!", "difficult": "~", "feature": "*"}
STATUS_KIND = {"blustering_gale": "beneficial", "cradled": "beneficial", "blade_of_light": "beneficial",
               "counter_spike": "beneficial", "guarding": "beneficial"}
STATUS_UNIT = {"broken": "until_source_turn_start", "frozen": "until_source_turn_start",
               "cradled": "until_source_turn_start", "blinded": "until_source_turn_end"}
ELEMENTAL_DETRIMENTAL = {"burning", "arts_seal", "frozen", "shadowed", "snowstorm", "blinded"}
COMBAT_TALENTS = {
    "immovable_gonzalez", "power_dive", "switch_art", "vendetta", "crisis_catalyst", "desperate_defense",
    "secondary_accelerator", "prime_position", "grand_procession", "tactical_delay", "the_last_laugh",
    "rematch", "your_patience_their_penitence", "what_goes_around", "dirty_fighter", "point_blank",
    "eagle_eye", "exit_strategy", "vanguard", "no_not_yet", "first_strike", "opportunist",
    "think_you_can_take_me", "villains_monologue", "say_sorry", "healer", "elite_healer", "master_healer",
    "youve_done_it_now", "stealth_strike", "to_me", "summon_art", "quick_step", "fleet_of_foot", "bondsight",
    "aura_field", "trebu_blade", "cut_the_cord", "protective_aegis", "final_flicker", "essence_exchange",
    "to_you", "living_amalgam", "distracting_strike", "mister_eddy", "radius_master", "swift_slide",
    "expeditionist", "premonitions", "forgotten_flash", "ghost_factory", "parry", "orbital_death_beam"}
AUTO_TALENTS = {"crisis_catalyst", "desperate_defense", "dirty_fighter", "protective_aegis",
                "final_flicker", "radius_master", "expeditionist", "healer"}


def _slug(t: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(t).strip().lower().replace("'", "")).strip("_")


def pair_key(a, b):
    x, y = sorted([str(a), str(b)])
    return f"{x}|{y}"


def _man(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _pos(p, what="position"):
    try:
        x, y = p
        return [int(x), int(y)]
    except Exception:
        raise GameError(f"{what} must be [x, y], got {p!r}")


def _sgn(n):
    return (n > 0) - (n < 0)


def _line_cells(a, b):
    x0, y0 = a
    x1, y1 = b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, pts = dx + dy, []
    while True:
        pts.append((x0, y0))
        if (x0, y0) == (x1, y1):
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return pts


class Ctx:
    """Per-call context: engine, state, combat, accumulated warnings/events."""

    def __init__(self, engine, st, force=False, need_combat=True):
        self.engine, self.st, self.force = engine, st, bool(force)
        self.combat = st.get("combat")
        if need_combat and not self.combat:
            raise GameError("no active combat: call combat_start first")
        self.warnings: list[str] = []
        self.events: list[str] = []

    # --- lookup
    def find(self, ref) -> dict:
        cs = self.combat["combatants"]
        if ref in cs:
            return cs[ref]
        r = str(ref).strip().lower()
        for c in cs.values():
            if r in (c["cid"].lower(), c["name"].lower(), c["short"].lower()):
                return c
        hits = [c for c in cs.values() if c["name"].lower().startswith(r) or c["cid"].lower().startswith(r)]
        if len(hits) == 1:
            return hits[0]
        raise GameError(f"unknown combatant {ref!r} (known: {', '.join(cs)})")

    def char(self, c):
        return self.st["characters"].get(c.get("char_id")) if c.get("char_id") else None

    def talents(self, c):
        ch = self.char(c)
        return ch.get("talents", []) if ch else []

    def has_talent(self, c, tid):
        return any(_slug(t.get("id") or "") == tid or _slug(t.get("name") or "") == tid
                   for t in self.talents(c))

    def derived(self, c, key, default):
        ch = self.char(c)
        if ch:
            return (ch.get("derived") or {}).get(key, default)
        card = c.get("card") or {}
        return {"movement": card.get("movement", default), "max_radius": card.get("max_radius", default),
                "basic_range": card.get("range", default)}.get(key, default)

    def attr(self, c, name):
        ch = self.char(c)
        if not ch:
            raise GameError(f"{c['name']} is an NPC; NPCs never roll (use combat_npc_attack)")
        a = ch.get("attributes", {})
        n = _slug(name)
        if n not in a:
            raise GameError(f"unknown attribute {name!r}; valid: {', '.join(a)}")
        return n, int(a[n])

    def check(self, ok, msg):
        """Rule check: raise unless force (then record a warning). Returns ok."""
        if not ok:
            if self.force:
                self.warnings.append(msg + " (forced)")
            else:
                raise GameError(msg + " (pass force=true to override)")
        return ok

    @property
    def current(self):
        o = self.combat["order"]
        return self.combat["combatants"][o[0]] if o else None

    def ev(self, text):
        self.events.append(text)
        self.combat["log"].append({"turn": self.combat["turns_taken"], "text": text})
        del self.combat["log"][:-80]

    def allies(self, a, b):
        sa, sb = a["side"], b["side"]
        return sa == sb or {sa, sb} == {"party", "neutral"}

    def team_of(self, c):
        return c.get("team_id") or c["cid"]


# ---------------------------------------------------------------- map helpers
def _cell(combat, p):
    return combat["map"]["cells"].get(f"{p[0]},{p[1]}")


def _in_map(combat, p):
    return 0 <= p[0] < combat["map"]["width"] and 0 <= p[1] < combat["map"]["height"]


def _blocks_move(combat, p):
    c = _cell(combat, p)
    return bool(c and c.get("blocks_move"))


def _blocks_sight(combat, p):
    c = _cell(combat, p)
    return bool(c and c.get("blocks_sight"))


def _occupant(combat, p, ignore=None):
    for c in combat["combatants"].values():
        if not c["down"] and c["pos"] == list(p) and c["cid"] != ignore:
            return c
    return None


def _free(combat, p, ignore=None):
    return _in_map(combat, p) and not _blocks_move(combat, p) and _occupant(combat, p, ignore) is None


def _los(combat, a, b):
    def clear(p, q):
        return not any(_blocks_sight(combat, pt) for pt in _line_cells(p, q)[1:-1])
    return clear(a, b) or clear(b, a)


def _build_map(m: dict) -> dict:
    if not isinstance(m, dict):
        raise GameError("map must be {width, height, name?, cells?: [...]}")
    try:
        w, h = int(m["width"]), int(m["height"])
    except Exception:
        raise GameError("map needs integer width and height")
    if not (1 <= w <= 60 and 1 <= h <= 60):
        raise GameError("map width/height must be 1..60")
    cells = {}
    for e in m.get("cells") or []:
        x, y = int(e["x"]), int(e["y"])
        if not (0 <= x < w and 0 <= y < h):
            raise GameError(f"cell ({x},{y}) is outside the {w}x{h} map")
        t = e.get("type", "obstacle")
        if t not in CELL_DEFAULTS:
            raise GameError(f"cell type {t!r} invalid; use {', '.join(CELL_DEFAULTS)}")
        bm, bs = CELL_DEFAULTS[t]
        cells[f"{x},{y}"] = {"type": t, "label": e.get("label", ""),
                             "blocks_move": bool(e.get("blocks_move", bm)),
                             "blocks_sight": bool(e.get("blocks_sight", bs)), "note": e.get("note", "")}
    return {"name": m.get("name", ""), "width": w, "height": h, "cells": cells}


# ---------------------------------------------------------------- blades / radius
def _bearer_of(combat, c):
    b = combat["combatants"].get(c.get("bearer_cid")) if c.get("bearer_cid") else None
    return b if b and not b["down"] else None


def _max_radius(ctx, c):
    return int(ctx.derived(c, "max_radius", 3) or 3)


def _status(c, sid):
    for s in c["statuses"]:
        if s["id"] == sid:
            return s
    return None


def _free_radius(c):
    s = _status(c, "blade_of_light")
    return bool(s and s["data"].get("blade_free"))


def _radius(combat, c):
    b = _bearer_of(combat, c)
    return max(1, _cheb(c["pos"], b["pos"])) if b and c["role"] == "blade" else None


def _zone(ctx, c, pos=None):
    b = _bearer_of(ctx.combat, c)
    r = max(1, _cheb(pos or c["pos"], b["pos"]))
    mr = _max_radius(ctx, c)
    return r if r <= mr else mr + 1


def _radius_effect(ctx, c):
    """None | ('third', r) | ('outside', r) for a Blade."""
    if c["role"] != "blade" or _free_radius(c):
        return None
    r = _radius(ctx.combat, c)
    if r is None:
        return None
    mr = _max_radius(ctx, c)
    if r > mr:
        return ("outside", r)
    if r >= 3 and not (r == 3 and ctx.has_talent(c, "radius_master")):
        return ("third", r)
    return None


def _low_hp(c):
    return c["hp"] <= c["max_hp"] // 4


def _attack_mods(ctx, c):
    """Auto pool modifiers for attack rolls: ([(label, value)], half_mode|None)."""
    mods, half = [], None
    if ctx.has_talent(c, "crisis_catalyst") and _low_hp(c):
        mods.append(("crisis catalyst", 2))
    if _status(c, "blinded"):
        mods.append(("blinded", -1))
    re_ = _radius_effect(ctx, c)
    if re_ and re_[0] == "third":
        mods.append((f"radius {re_[1]}", -1))
    elif re_:
        half = "exped" if ctx.has_talent(c, "expeditionist") else "half"
    return mods, half


def _defense_mods(ctx, c):
    mods, half = [], None
    if _status(c, "blustering_gale"):
        mods.append(("blustering gale", 1))
    if _status(c, "blinded"):
        mods.append(("blinded", -1))
    if ctx.has_talent(c, "desperate_defense") and _low_hp(c):
        mods.append(("desperate defense", 2))
    re_ = _radius_effect(ctx, c)
    if re_ and re_[0] == "third":
        mods.append((f"radius {re_[1]}", -1))
    elif re_:
        half = "exped" if ctx.has_talent(c, "expeditionist") else "half"
    return mods, half


# ---------------------------------------------------------------- rolls
def _do_roll(ctx, c, label, kind, attribute, base, mods, half=None):
    mods = list(mods)
    total = base + sum(v for _, v in mods)
    if half and total > 0:
        new = max(math.ceil(total / 2), total - 3) if half == "exped" else math.ceil(total / 2)
        mods.append(("outside max radius (half dice)", new - total))
        total = new
    floor = total < 1
    pool = max(1, total)
    dice = ctx.engine.roller.roll(pool)
    return {"c": c, "label": label, "kind": kind, "attribute": attribute, "pool": pool, "mods": mods,
            "dice": dice, "successes": count_successes(dice), "floor": floor, "base": base}


def _record(ctx, r, check, net, damage=None, auto=None, note=""):
    c = r["c"]
    fields = dict(who=c["name"], char_id=c.get("char_id"), label=r["label"], kind=r["kind"],
                  attribute=r["attribute"], pool=r["pool"],
                  mods=[{"label": l, "value": v} for l, v in r["mods"]], dice=r["dice"],
                  successes=r["successes"], check=check, net=net, tier=_tier(net), auto=auto,
                  damage=damage, note=note)
    if r["floor"]:
        fields["pool_floor"] = True
    return ctx.engine.record_roll(**fields)


def _pool_text(r):
    parts = [f"{r['attribute']} {r['base']}" if r["base"] is not None else "pool"]
    for l, v in r["mods"]:
        parts.append(f"{v:+d} {l}")
    return (" ".join(parts) + f" = {r['pool']} dice: " + ",".join(str(x) for x in r["dice"])
            + f" -> {r['successes']} success" + ("" if r["successes"] == 1 else "es"))


TIER_TEXT = {"success": "hit", "near_hit": "near hit", "near_miss": "near miss", "failure": "miss"}


# ---------------------------------------------------------------- statuses
def _add_status(ctx, target, sid, remaining, unit=None, source=None, data=None, label=None, kind=None):
    kind = kind or STATUS_KIND.get(sid, "detrimental")
    unit = unit or STATUS_UNIT.get(sid, "own_turns")
    if sid in ELEMENTAL_DETRIMENTAL and _status(target, "cradled"):
        ctx.ev(f"{target['name']} is cradled: {sid} blocked")
        return None
    remaining = max(1, min(6, int(remaining)))
    cur = ctx.current
    data = dict(data or {})
    fresh = (unit == "own_turns" and cur is target) or (unit == "until_source_turn_end" and cur
                                                        and cur["cid"] == source)
    if fresh:
        data["fresh"] = True
    ex = _status(target, sid)
    if ex:
        ex["remaining"] = min(6, ex["remaining"] + remaining)
        ex["data"].update(data)
        return ex
    s = {"id": sid, "label": label or sid, "kind": kind, "remaining": remaining, "unit": unit,
         "source": source, "data": data}
    target["statuses"].append(s)
    return s


def _remove_status(target, sid):
    n = len(target["statuses"])
    target["statuses"] = [s for s in target["statuses"] if s["id"] != sid]
    return len(target["statuses"]) != n


def _st_str(ctx, s):
    src = ctx.combat["combatants"].get(s["source"], {}).get("name", s["source"]) if s["source"] else "?"
    if s["unit"] == "own_turns":
        return f"{s['id']}:{s['remaining']}t"
    x = f" x{s['remaining']}" if s["remaining"] > 1 else ""
    if s["unit"] == "until_source_turn_start":
        return f"{s['id']}(until {src}'s next turn{x})"
    return f"{s['id']}(until {src}'s turn ends{x})"


# ---------------------------------------------------------------- order / special
def _shift(order, cid, delta):
    if cid not in order:
        return
    i = order.index(cid)
    j = max(0, min(len(order) - 1, i - int(delta)))
    order.insert(j, order.pop(i))


def _add_special(ctx, team, n):
    pts = ctx.combat["special"]["points"]
    old = pts.get(team, 0)
    pts[team] = max(0, min(18, old + n))
    return old, pts[team]


def _dice_str(p):
    if p <= 0:
        return "-"
    return ",".join(["6"] * (p // 6) + ([str(p % 6)] if p % 6 else []))


def _check_end(combat) -> Optional[str]:
    cs = combat["combatants"].values()
    party = [c for c in cs if c["side"] == "party"]
    foes = [c for c in cs if c["side"] == "enemy"]
    if party and all(c["down"] for c in party):
        return "party is fully down"
    if foes and all(c["down"] for c in foes):
        return "all enemies are down"
    return None


# ---------------------------------------------------------------- damage / down / life force
def _natural_blade(ctx, b):
    return not (ctx.has_talent(b, "artificial_core") or ctx.has_talent(b, "flesh_eater"))


def _set_down(ctx, c, why=""):
    if c["down"]:
        return
    c["hp"], c["down"] = 0, True
    cb = ctx.combat
    if c["cid"] in cb["order"]:
        cb["order"].remove(c["cid"])
    for o in cb["combatants"].values():
        o["statuses"] = [s for s in o["statuses"]
                         if not (s["source"] == c["cid"] and s["unit"].startswith("until_source"))]
    ctx.ev(f"{c['name']} is down" + (f" ({why})" if why else ""))
    for bid in c.get("blade_cids", []):
        b = cb["combatants"].get(bid)
        if b and not b["down"] and _natural_blade(ctx, b):
            _set_down(ctx, b, f"bearer {c['name']} fell")


def _lf_options(ctx, bearer):
    opts = []
    for bid in bearer.get("blade_cids", []):
        b = bearer and ctx.combat["combatants"][bid]
        if b["down"] or b["hp"] < 1:
            continue
        aegis = ctx.has_talent(b, "protective_aegis")
        flick = ctx.has_talent(b, "final_flicker")
        need1 = (1 - bearer["hp"]) + (0 if aegis else 1)
        if b["hp"] >= need1 or flick:
            opts.append({"cid": bid, "hp": b["hp"], "cost_for_1": need1, "aegis": aegis, "flicker": flick,
                         "max_give": max(0, b["hp"] + bearer["hp"] - (0 if aegis else 1))})
    return opts


def _damage(ctx, t, n, cause=""):
    """Apply damage; may start life-force pending or down. Returns damage applied."""
    n = int(n)
    if n <= 0 or t["down"]:
        return 0
    cb = ctx.combat
    was_pending = t["hp"] <= 0
    t["hp"] -= n
    if t["hp"] > 0:
        return n
    if was_pending:
        for p in [cb["pending"]] + cb.get("pending_more", []):
            if p and p.get("type") == "life_force" and p["bearer"] == t["cid"]:
                p["hp_after"] = t["hp"]
                p["blades"] = _lf_options(ctx, t)
        return n
    if t["kind"] == "pc" and t["role"] == "bearer":
        opts = _lf_options(ctx, t)
        if opts:
            p = {"type": "life_force", "bearer": t["cid"], "hp_after": t["hp"], "blades": opts}
            if cb["pending"]:
                cb.setdefault("pending_more", []).append(p)
            else:
                cb["pending"] = p
            ctx.ev(f"{t['name']} would drop to {t['hp']} HP: Life Force Sharing pending "
                   f"(blades: {', '.join(o['cid'] for o in opts)}); resolve with combat_life_force")
            return n
    _set_down(ctx, t, cause)
    return n


def _heal(ctx, t, n):
    if t["down"] or n <= 0:
        return 0
    new = min(t["max_hp"], max(t["hp"], 0) + n)
    got = new - max(t["hp"], 0)
    t["hp"] = new
    return got


def _next_pending(cb):
    more = cb.get("pending_more") or []
    cb["pending"] = more.pop(0) if more else None


# ---------------------------------------------------------------- turn start / end
def _reset_turn(c):
    c["turn"] = {"moved": 0, "radius_moves": 0, "acted": False, "attacked": False, "bonus_move": 0,
                 "dealt_damage": False, "swapped": False}


def _start_turn(ctx, c):
    if c.get("start_applied"):
        return
    c["start_applied"] = True
    _reset_turn(c)
    c.pop("follow_opt", None)
    keep = []
    for s in c["statuses"]:
        keep.append(s)
    for o in ctx.combat["combatants"].values():
        out = []
        for s in o["statuses"]:
            if s["unit"] == "until_source_turn_start" and s["source"] == c["cid"]:
                s["remaining"] -= 1
                if s["remaining"] <= 0:
                    ctx.ev(f"{s['id']} on {o['name']} expires")
                    continue
            out.append(s)
        o["statuses"] = out
    if _status(c, "burning"):
        d = _damage(ctx, c, 1, "burning")
        ctx.ev(f"{c['name']} takes {d} burning damage (hp {c['hp']}/{c['max_hp']})")


def _advance(ctx):
    """Start turns until a living actor is first in order (burn-downs are skipped)."""
    cb = ctx.combat
    while cb["order"]:
        c = cb["combatants"][cb["order"][0]]
        _start_turn(ctx, c)
        if not c["down"]:
            return c
    return None


def _tick_cooldowns(c):
    c["cooldowns"] = [0 if v <= 1 else v - 1 for v in c.get("cooldowns") or []]


def _end_of_turn(ctx, a):
    """Cooldowns, status ticks, swap lock for actor `a` (does not rotate)."""
    if a["kind"] == "pc" and not _status(a, "arts_seal"):
        _tick_cooldowns(a)
    keep = []
    for s in a["statuses"]:
        if s["unit"] == "own_turns":
            if s["data"].pop("fresh", False):
                keep.append(s)
                continue
            s["remaining"] -= 1
            if s["remaining"] <= 0:
                ctx.ev(f"{s['id']} on {a['name']} ends")
                continue
        keep.append(s)
    a["statuses"] = keep
    for o in ctx.combat["combatants"].values():
        out = []
        for s in o["statuses"]:
            if s["unit"] == "until_source_turn_end" and s["source"] == a["cid"]:
                if s["data"].pop("fresh", False):
                    out.append(s)
                    continue
                s["remaining"] -= 1
                if s["remaining"] <= 0:
                    ctx.ev(f"{s['id']} on {o['name']} ends")
                    continue
            out.append(s)
        o["statuses"] = out
    lock = ctx.combat.get("swap_lock", {})
    for tid in list(lock):
        if a["cid"] in lock[tid]:
            lock[tid].remove(a["cid"])
        if not lock[tid]:
            del lock[tid]
    a["start_applied"] = False


# ---------------------------------------------------------------- building combatants
def _load_bestiary():
    p = Path(__file__).parent / "data" / "bestiary.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    lst = d.get("enemies", d) if isinstance(d, dict) else d
    return {e.get("id"): e for e in lst if isinstance(e, dict)}


def _tri(v, default=1):
    if isinstance(v, (int, float)):
        return {"dis": int(v), "normal": int(v), "adv": int(v)}
    v = dict(v or {})
    n = int(v.get("normal", v.get("dis", v.get("adv", default))))
    return {"dis": int(v.get("dis", n)), "normal": n, "adv": int(v.get("adv", n))}


def _norm_card(raw: dict) -> dict:
    return {"role": raw.get("role", "other"), "attack": _tri(raw.get("attack")),
            "defense": _tri(raw.get("defense"), 0), "hp": int(raw.get("hp", 3)),
            "movement": int(raw.get("movement", 3)), "initiative": int(raw.get("initiative", 0)),
            "affinities": list(raw.get("affinities") or []), "best_attributes": list(raw.get("best_attributes") or []),
            "art_tags": list(raw.get("art_tags") or []),
            "special_abilities": list(raw.get("special_abilities") or []), "notes": raw.get("notes", "")}


def _short(combat, name, upper):
    used = {c["short"] for c in combat["combatants"].values()}
    letters = [ch for ch in name if ch.isalpha()] or ["x"]
    for ch in letters + list("abcdefghijklmnopqrstuvwxyz"):
        ch = ch.upper() if upper else ch.lower()
        for k in range(1, 10):
            if f"{ch}{k}" not in used:
                return f"{ch}{k}"
    return "??"


def _build_combatant(ctx, e: dict, combat: dict, cooldown_order=None, name_override=None):
    st = ctx.st
    pos = _pos(e.get("pos"), "pos")
    if not _in_map(combat, pos):
        raise GameError(f"pos {pos} is outside the map")
    if _blocks_move(combat, pos):
        ctx.check(False, f"pos {pos} is a blocked terrain cell")
    if _occupant(combat, pos):
        ctx.check(False, f"pos {pos} is already occupied by {_occupant(combat, pos)['name']}")
    c = {"pos": pos, "down": False, "statuses": [], "combat_talents_used": [], "blade_cids": [],
         "bearer_cid": None, "card": None, "cooldowns": [], "char_id": None}
    if e.get("char_id"):
        ch = st["characters"].get(e["char_id"])
        if not ch:
            raise GameError(f"unknown char_id {e['char_id']!r}")
        if ch.get("dead"):
            raise GameError(f"{ch['name']} is dead")
        d = ch.get("derived") or {}
        maxhp = int(d.get("max_hp", 10))
        hp = int(e.get("hp", ch.get("hp") if ch.get("hp") is not None else maxhp))
        if hp <= 0:
            ctx.check(False, f"{ch['name']} has {hp} HP")
        c.update(cid=ch["id"], name=ch["name"], kind="pc", char_id=ch["id"], side=e.get("side", "party"),
                 role=ch.get("role", "bearer"), team_id=ch.get("team_id"), hp=min(hp, maxhp), max_hp=maxhp,
                 facing=e.get("facing", "N"))
        n = max(3, len(ch.get("arts", [])))
        sc = list(d.get("start_cooldowns", [0, 2, 4]))
        order = (cooldown_order or {}).get(ch["id"]) or list(range(min(n, len(sc))))
        if sorted(order) != list(range(len(order))) or len(order) > len(sc):
            raise GameError(f"cooldown_order for {ch['id']} must be a permutation of art indices 0..{len(sc)-1}")
        cds = [0] * max(len(order), n)
        for k, art_i in enumerate(order):
            cds[art_i] = sc[k]
        c["cooldowns"] = cds
    else:
        if not e.get("name") and not e.get("bestiary"):
            raise GameError("NPC entry needs name + card, or bestiary id")
        raw = {}
        if e.get("bestiary"):
            bst = _load_bestiary()
            if bst is None:
                raise GameError("bestiary.json is unavailable; pass an explicit card instead of bestiary")
            if e["bestiary"] not in bst:
                raise GameError(f"bestiary id {e['bestiary']!r} unknown; known: {', '.join(sorted(bst))}")
            raw = dict(bst[e["bestiary"]])
        raw.update(e.get("card") or {})
        if not raw:
            raise GameError(f"NPC {e.get('name')!r} needs a card or bestiary id")
        card = _norm_card(raw)
        name = name_override or e.get("name") or raw.get("name") or e["bestiary"]
        cid = _slug(name) or "npc"
        base, k = cid, 2
        while cid in combat["combatants"]:
            cid, k = f"{base}_{k}", k + 1
        hp = int(e.get("hp", card["hp"]))
        c.update(cid=cid, name=name, kind="npc", side=e.get("side", "enemy"), role=e.get("role", card["role"]),
                 team_id=None, hp=hp, max_hp=max(hp, card["hp"]), card=card,
                 facing=e.get("facing", "S" if e.get("side", "enemy") == "enemy" else "N"))
    if c["facing"] not in DIRS:
        raise GameError("facing must be N, E, S or W")
    if c["side"] not in ("party", "enemy", "neutral"):
        raise GameError("side must be party, enemy or neutral")
    c["short"] = _short(combat, c["name"], c["kind"] == "pc")
    _reset_turn(c)
    c["start_applied"] = False
    return c


def _link_bearers(ctx, combat, entries):
    cs = combat["combatants"]
    for c in list(cs.values()):
        if c["role"] != "blade":
            continue
        b = None
        if c["kind"] == "pc":
            tm = ctx.st["teams"].get(c.get("team_id")) or {}
            b = cs.get(tm.get("bearer"))
        else:
            ref = entries.get(c["cid"], {}).get("bearer")
            if ref:
                b = ctx.find(ref)
        if b is None:
            ctx.warnings.append(f"Blade {c['name']} has no Bearer in this combat: no radius rules apply")
            continue
        c["bearer_cid"] = b["cid"]
        if c["cid"] not in b["blade_cids"]:
            b["blade_cids"].append(c["cid"])


def combat_start(engine, name, map, combatants, feeling_it=None, cooldown_order=None, ambush=None,
                 team_order=None, force=False):
    with engine.txn("combat_start") as st:
        ctx = Ctx(engine, st, force, need_combat=False)
        if st.get("combat"):
            ctx.check(False, "a combat is already active (combat_end it first)")
        if ambush not in (None, "party", "enemy"):
            raise GameError("ambush must be null, 'party' or 'enemy'")
        cb = {"id": f"combat{st['clock'].get('combats', 0) + 1}", "name": name, "turns_taken": 0,
              "map": _build_map(map), "combatants": {}, "order": [], "pending_shifts": [],
              "special": {"chain_level": 0, "points": {}}, "pending": None, "pending_more": [],
              "swap_lock": {}, "log": []}
        ctx.combat = cb
        entries = {}
        names = {}
        for e in combatants:
            if not e.get("char_id"):
                nm = e.get("name") or (e.get("bestiary") and (_load_bestiary() or {}).get(e["bestiary"], {})
                                       .get("name", e["bestiary"]))
                names[nm] = names.get(nm, 0) + 1
        seen = {}
        for e in combatants:
            ov = None
            if not e.get("char_id"):
                nm = e.get("name") or (e.get("bestiary") and (_load_bestiary() or {}).get(e["bestiary"], {})
                                       .get("name", e["bestiary"]))
                if names.get(nm, 0) > 1:
                    seen[nm] = seen.get(nm, 0) + 1
                    ov = f"{nm} {seen[nm]}"
            c = _build_combatant(ctx, e, cb, cooldown_order, ov)
            cb["combatants"][c["cid"]] = c
            entries[c["cid"]] = e
        if not cb["combatants"]:
            raise GameError("combat needs combatants")
        _link_bearers(ctx, cb, entries)
        for c in cb["combatants"].values():
            if c["kind"] == "pc":
                cb["special"]["points"].setdefault(ctx.team_of(c), 0)
                if c["role"] == "blade" and c["bearer_cid"]:
                    r = _radius(cb, c)
                    if r > _max_radius(ctx, c):
                        ctx.warnings.append(f"{c['name']} starts outside max radius")
        # initiative
        slots, init_info, seq = [], [], 0
        for c in cb["combatants"].values():
            seq += 1
            if c["kind"] == "npc":
                slots.append({"res": c["card"]["initiative"], "pool": 0, "seq": seq, "cid": c["cid"],
                              "team": None, "side": c["side"]})
                init_info.append(f"{c['cid']}:{c['card']['initiative']}(static)")
                continue
            ch = ctx.char(c)
            pool = int((ch.get("derived") or {}).get("initiative_pool", 2))
            mods = []
            fi = next((f for f in (feeling_it or []) if f.get("char_id") == c["cid"]), None)
            if fi:
                an, av = ctx.attr(c, fi.get("attribute", ""))
                ab = ch.setdefault("arc_abilities", {})
                ctx.check(ab.get("feeling_it", True), f"{c['name']} already used I'm Really Feeling It this arc")
                ab["feeling_it"] = False
                mods.append((f"feeling it ({an})", av))
                _add_special(ctx, ctx.team_of(c), 6)
                ctx.ev(f"{c['name']} uses I'm Really Feeling It: +{an}, team gains 6 special points")
            r = _do_roll(ctx, c, "initiative", "initiative", None, pool, mods)
            _record(ctx, r, 0, r["successes"], note="initiative")
            slots.append({"res": r["successes"], "pool": r["pool"], "seq": seq, "cid": c["cid"],
                          "team": ctx.team_of(c), "side": c["side"]})
            init_info.append(f"{c['cid']}:{r['successes']}(pool {r['pool']}: {','.join(str(x) for x in r['dice'])})")
        slots.sort(key=lambda s: (-s["res"], -s["pool"], s["seq"]))
        # team slots: members take slots in team_order (default: whoever rolled it)
        for team, members in (team_order or {}).items():
            idx = [i for i, s in enumerate(slots) if s["team"] == team]
            if sorted(members) != sorted(slots[i]["cid"] for i in idx):
                raise GameError(f"team_order[{team}] must list exactly the team's combatants")
            for i, m in zip(idx, members):
                slots[i]["cid"] = m
        if ambush:
            allied = lambda s: s["side"] in ("party", "neutral")  # noqa: E731
            first = [s for s in slots if allied(s) == (ambush == "party")]
            slots = first + [s for s in slots if s not in first]
        cb["order"] = [s["cid"] for s in slots]
        st["combat"] = cb
        first = _advance(ctx)
        res = {"ok": True,
               "summary": f"Combat '{name}' begins: {len(cb['combatants'])} combatants; order "
                          + ", ".join(cb["combatants"][i]["name"] for i in cb["order"])
                          + f"; {first['name']} acts first." + (f" Ambush: {ambush} acts first." if ambush else ""),
               "initiative": init_info}
        res.update(_context(ctx, first))
        return _finish(ctx, res)


_PENDING_TOOL = {"life_force": "combat_life_force", "special_split": "combat_special_assign"}


def _nearest_free(cb, pos, cid):
    best = None
    for dx in range(-6, 7):
        for dy in range(-6, 7):
            q = [pos[0] + dx, pos[1] + dy]
            if _in_map(cb, q) and _free(cb, q, cid):
                d = abs(dx) + abs(dy)
                if best is None or d < best[0]:
                    best = (d, q)
    return best[1] if best else None


def _pending_hint(cb):
    """Human/AI-readable instruction for whatever the engine is waiting on (None if nothing pending)."""
    p = cb.get("pending") if cb else None
    if not p:
        return None
    if p["type"] == "life_force":
        c = cb["combatants"].get(p.get("bearer"), {})
        return (f"WAITING: {c.get('name', 'the Bearer')} would drop to {p.get('hp_after')} HP. Ask the player, then call "
                f"combat_life_force(give=<HP to restore the Bearer to, >=1>) or combat_life_force(decline=true) "
                f"(blades able to pay: {', '.join(b['cid'] for b in p.get('blades', [])) or 'none'}).")
    if p["type"] == "special_split":
        return (f"WAITING: divide {p.get('total')} special damage among {p.get('candidates')}: call "
                f"combat_special_assign(allocations={{cid: damage}}) summing to {p.get('total')} (leave allies out to spare them).")
    return f"WAITING on pending {p['type']}."


def _pending_error(cb):
    p = cb["pending"]
    tool = _PENDING_TOOL.get(p["type"], "the matching resolve tool")
    return f"resolve the pending {p['type']} first: call {tool} ({_pending_hint(cb)})"


def _finish(ctx, res):
    if ctx.warnings:
        res["warnings"] = ctx.warnings
    if ctx.events:
        res["events"] = ctx.events
    end = _check_end(ctx.combat)
    if end:
        res["suggest_end"] = True
        res["end_reason"] = end
    if ctx.combat.get("pending"):
        res["pending"] = ctx.combat["pending"]
        res["next"] = _pending_hint(ctx.combat)
    return res


# ---------------------------------------------------------------- movement budget helpers
def _base_move(ctx, c):
    m = int(ctx.derived(c, "movement", 3) or 0)
    if _status(c, "snowstorm"):
        m = max(0, m - 1)
    return m


def _is_radius_mover(ctx, c):
    return c["role"] == "blade" and _bearer_of(ctx.combat, c) is not None


def _move_state(ctx, c):
    base = _base_move(ctx, c)
    t = c["turn"]
    used = t["radius_moves"] if _is_radius_mover(ctx, c) else t["moved"]
    engaged = t["attacked"]
    limit = (base if engaged else base * 2) + t["bonus_move"]
    return {"base": base, "used": used, "limit": limit, "left": max(0, limit - used),
            "left_if_attacking": max(0, base - used) if used <= base else None}


# ---------------------------------------------------------------- rendering
def _line(ctx, c):
    cb = ctx.combat
    if c["down"]:
        return f"{c['short']} {c['cid']} DOWN ({c['role']}, {c['side']})"
    s = f"{c['short']} {c['cid']} ({c['role']},{c['side']}) hp {c['hp']}/{c['max_hp']} @{c['pos'][0]},{c['pos'][1]}{ARROW[c['facing']]}"
    if c["kind"] == "pc":
        s += " cd[" + ",".join("r" if v == 0 else str(v) for v in c["cooldowns"]) + "]"
    r = _radius(cb, c)
    if r is not None:
        b = _bearer_of(cb, c)
        mr = _max_radius(ctx, c)
        s += f" radius {r}{'(OUTSIDE max ' + str(mr) + ')' if r > mr else ''} of {b['cid']}"
    if c["statuses"]:
        s += " st: " + ", ".join(_st_str(ctx, x) for x in c["statuses"])
    if cb["pending"] and cb["pending"].get("bearer") == c["cid"]:
        s += " [LIFE FORCE PENDING]"
    return s


def _render_map(ctx):
    cb = ctx.combat
    m = cb["map"]
    toks = {tuple(c["pos"]): c for c in cb["combatants"].values() if not c["down"]}
    rows = ["    " + "".join(f"{x:<4}" for x in range(m["width"]))]
    for y in range(m["height"]):
        row = f"{y:>2}  "
        for x in range(m["width"]):
            if (x, y) in toks:
                c = toks[(x, y)]
                row += c["short"] + ARROW[c["facing"]] + " "
            else:
                cell = m["cells"].get(f"{x},{y}")
                row += GLYPH[cell["type"]] * 3 + " " if cell else ".   "
        rows.append(row.rstrip())
    return "\n".join(rows)


def _legend(ctx):
    cb = ctx.combat
    bits = [f"{c['short']}={c['cid']}" for c in cb["combatants"].values() if not c["down"]]
    kinds = sorted({v["type"] for v in cb["map"]["cells"].values()})
    bits += [f"{GLYPH[k]}={k}" for k in kinds]
    labs = [f"({k})={v['label']}" for k, v in cb["map"]["cells"].items() if v.get("label")]
    return "; ".join(bits + labs) + "; arrows show facing (^N >E vS <W); x right, y down"


def _special_block(ctx):
    cb = ctx.combat
    sp = cb["special"]
    nxt = sp["chain_level"] + 1
    pts = sp["points"]
    teams = {}
    for t, p in pts.items():
        teams[t] = f"dice {_dice_str(p)} ({p} pts)" + ("; next special L%d usable" % nxt if p >= 6 * nxt else
                                                        "; L%d needs %d pts" % (nxt, 6 * nxt))
    note = ("one-team party: dice are only consumed by a level 3 special" if len(pts) == 1 else
            "two teams: level 2 gives the other team 6 points" if len(pts) == 2 else "")
    out = {"chain_level": sp["chain_level"], "next_level": nxt, "teams": teams}
    if note:
        out["rule"] = note
    return out


def _context(ctx, actor=None):
    cb = ctx.combat
    out = {"combat": cb["name"], "turns_taken": cb["turns_taken"], "map": _render_map(ctx),
           "legend": _legend(ctx),
           "order": [("-> " if i == 0 else "") + f"{cb['combatants'][x]['short']} {x}"
                     for i, x in enumerate(cb["order"])],
           "combatants": [_line(ctx, c) for c in cb["combatants"].values()],
           "special": _special_block(ctx)}
    if cb["pending_shifts"]:
        out["pending_shifts"] = cb["pending_shifts"]
    _end = _check_end(cb)
    if _end:
        out["suggest_end"] = True
        out["end_reason"] = _end
    if cb["pending"]:
        out["pending"] = cb["pending"]
        out["next"] = _pending_hint(cb)
    if actor is not None:
        out["actor"] = _actor_block(ctx, actor)
    return out


def _fmt_targets(ctx, a, ents):
    return ", ".join(ents) if ents else "none"


def _foes(ctx, a):
    return [c for c in ctx.combat["combatants"].values() if not c["down"] and not ctx.allies(a, c)]


def _range_of(ctx, a, tags, basic):
    if basic:
        r = int(ctx.derived(a, "basic_range", 1))
    else:
        r = (0 if (tags.get("circle") or tags.get("line")) else 1) + tags.get("range", 0)
    bl = _status(a, "blade_of_light")
    if bl and a["role"] != "blade":
        r += 2
    if _status(a, "snowstorm") and r >= 1:
        r = max(1, r - 1)
    return r


def _reach(ctx, a, tags, rng):
    """enemies hittable from the current square, as text entries."""
    out = []
    cb = ctx.combat
    rad = 0
    shape = "circle" if tags.get("circle") else "line" if tags.get("line") else None
    if shape == "circle":
        rad = tags["circle"]
    for f in _foes(ctx, a):
        d = _man(a["pos"], f["pos"])
        if shape == "line":
            al = (f["pos"][0] == a["pos"][0] or f["pos"][1] == a["pos"][1]) and d <= 5 + tags.get("range", 0)
            ok = al and _los(cb, a["pos"], f["pos"])
        else:
            ok = d <= rng + (rad * 2 if shape else 0) and _los(cb, a["pos"], f["pos"])
        if ok:
            ent = f"{f['cid']}(d{d})"
            if not shape and tags:
                bonus = _positional(ctx, a, f, tags)[0]
                if bonus:
                    ent += f"[+{bonus} positional]"
            out.append(ent)
    return out


def _actor_block(ctx, c):
    cb = ctx.combat
    b = {"cid": c["cid"], "name": c["name"], "pos": c["pos"], "facing": c["facing"],
         "hp": f"{c['hp']}/{c['max_hp']}"}
    toppled = _status(c, "toppled")
    b["must_skip"] = bool(toppled)
    ms = _move_state(ctx, c)
    if toppled or _status(c, "frozen") and c["role"] == "blade":
        ms["left"] = 0
    b["movement"] = ({"radius_moves": True, **ms} if _is_radius_mover(ctx, c) else ms)
    b["action_used"] = c["turn"]["acted"]
    mods, half = _attack_mods(ctx, c)
    auto = [f"{l} {v:+d}" for l, v in mods] + (["half dice (outside max radius)"] if half else [])
    b["auto_modifiers"] = auto
    att, rem = [], []
    if c["kind"] == "pc":
        ch = ctx.char(c)
        sealed = bool(_status(c, "arts_seal"))
        rng = _range_of(ctx, c, {}, True)
        att.append(f"basic: pool = chosen attribute{' ' + ', '.join(auto) if auto else ''}; range {rng}; "
                   f"in range: {_fmt_targets(ctx, c, _reach(ctx, c, {}, rng))}")
        for i, art in enumerate(ch.get("arts", [])):
            tags = art.get("tags", {})
            tagtxt = " ".join(f"{k}x{v}" if v > 1 else k for k, v in tags.items())
            cd = c["cooldowns"][i] if i < len(c["cooldowns"]) else 0
            if cd:
                att.append(f"art {i} '{art['name']}' [{tagtxt}] on cooldown {cd}")
            elif sealed:
                att.append(f"art {i} '{art['name']}' [{tagtxt}] SEALED this turn")
            else:
                r = _range_of(ctx, c, tags, False)
                shape = ("circle %dx%d" % (2 * tags["circle"] + 1,) * 2 if False else "")
                if tags.get("circle"):
                    shape = f" circle {2 * tags['circle'] + 1}x{2 * tags['circle'] + 1} centred <= {r} away"
                elif tags.get("line"):
                    shape = f" line {5 + tags.get('range', 0)} long"
                att.append(f"art {i} '{art['name']}' [{tagtxt}] +{tags.get('potency', 0)} potency; range {r}{shape}; "
                           f"in range: {_fmt_targets(ctx, c, _reach(ctx, c, tags, r))}")
        tl = []
        for t in ch.get("talents", []):
            s = _slug(t.get("id") or t.get("name"))
            if s in COMBAT_TALENTS or _slug(t.get("name", "")) in COMBAT_TALENTS:
                tl.append(t["name"] + (" (auto)" if s in AUTO_TALENTS else "") +
                          (" [used]" if t.get("used") and t.get("per") == "combat" else ""))
        if tl:
            b["combat_talents"] = tl
        if ctx.has_talent(c, "crisis_catalyst") and _low_hp(c):
            rem.append("Crisis Catalyst applies: +2 attack rolls (auto)")
        if ctx.has_talent(c, "desperate_defense") and _low_hp(c):
            rem.append("Desperate Defense applies: +2 defense rolls (auto in defenders)")
        if c["role"] == "blade":
            bb = _bearer_of(cb, c)
            if bb and _low_hp(bb):
                rem.append("bearer at <= quarter HP: Crisis Catalyst applies if the bearer has it; protect them")
    else:
        card = c["card"]
        rng = int(card.get("range", 1))
        reach = [f"{f['cid']}(d{_man(c['pos'], f['pos'])})" for f in _foes(ctx, c)
                 if _man(c["pos"], f["pos"]) <= rng and _los(cb, c["pos"], f["pos"])]
        a_ = card["attack"]
        att.append(f"attack values dis/normal/adv = {a_['dis']}/{a_['normal']}/{a_['adv']}; range {rng}; "
                   f"in range: {_fmt_targets(ctx, c, reach)}; art tags available: {card['art_tags'] or 'none'}")
        b["card"] = card
        b["card_defense"] = card["defense"]
        if c["role"] == "blade" and _radius_effect(ctx, c):
            rem.append("NPC Blade out in a high radius: consider -1 to its attack/defense value")
    b["attacks"] = att
    if toppled:
        rem.append("toppled: must skip (cannot move or act; end the turn). It can still defend.")
    s = _status(c, "arts_seal")
    if s:
        rem.append("arts sealed: no arts this turn and cooldowns do not tick")
    if _status(c, "frozen"):
        rem.append("frozen: " + ("cannot move at all" if c["role"] == "blade" else "cannot move"
                                 + ("; its Blade is stuck in its radius" if c["blade_cids"] else "")))
    s = _status(c, "shadowed")
    if s:
        rem.append(f"shadowed: may only attack {s['data'].get('only_target')}")
    if _status(c, "snowstorm"):
        rem.append("snowstorm: -1 movement and -1 attack range (auto)")
    re_ = _radius_effect(ctx, c)
    if re_ and re_[0] == "third":
        rem.append(f"Blade in radius {re_[1]}: -1 to all actions (auto)")
    elif re_:
        rem.append("Blade outside max radius: half dice, 1 square per turn (auto)")
    if _status(c, "blade_of_light") and c["role"] == "blade":
        rem.append("Blade of Light: move freely among all radii this turn, no penalties")
    if c["role"] == "blade" and c.get("follow_opt"):
        rem.append(f"bearer moved: you may combat_move follow=true to return to radius {c['follow_opt']['radius']}")
    if c["role"] == "bearer" and c["blade_cids"]:
        rem.append("blades: " + ", ".join(f"{x} radius {_radius(cb, cb['combatants'][x])}"
                                          for x in c["blade_cids"] if not cb["combatants"][x]["down"]))
    if c["turn"]["bonus_move"]:
        rem.append(f"rush: +{c['turn']['bonus_move']} bonus movement after attacking")
    b["reminders"] = rem
    return b


def combat_state(engine, cid=None):
    st = engine.require_state()
    ctx = Ctx(engine, st)
    actor = None
    if cid:
        actor = ctx.current if cid == "current" else ctx.find(cid)
    res = {"ok": True}
    res.update(_context(ctx, actor))
    return res


# ---------------------------------------------------------------- turn gating
def _require_actor(ctx, a, action, offensive=True):
    cb = ctx.combat
    ctx.check(not cb["pending"], _pending_error(cb) if cb["pending"] else "")
    if a["down"]:
        raise GameError(f"{a['name']} is down")
    cur = ctx.current
    ctx.check(cur is a, f"it is not {a['name']}'s turn (current actor: {cur['name'] if cur else 'nobody'})")
    ctx.check(not _status(a, "toppled"), f"{a['name']} is toppled and cannot move or act this turn")
    if action:
        ctx.check(not a["turn"]["acted"], f"{a['name']} already used their action this turn")
        if offensive:
            used = a["turn"]["radius_moves"] if _is_radius_mover(ctx, a) else a["turn"]["moved"]
            ctx.check(used <= _base_move(ctx, a),
                      f"{a['name']} moved more than normal movement this turn, so cannot attack/engage")


# ---------------------------------------------------------------- positional
def _facing_options(a, t):
    dx, dy = t["pos"][0] - a["pos"][0], t["pos"][1] - a["pos"][1]
    if abs(dx) > abs(dy):
        return ["E" if dx > 0 else "W"]
    if abs(dy) > abs(dx):
        return ["S" if dy > 0 else "N"]
    return ["E" if dx > 0 else "W", "S" if dy > 0 else "N"]


def _positional(ctx, a, t, tags, face=None):
    """(bonus, label, attacker_facing, rel). Computed before the target turns."""
    opts = _facing_options(a, t)
    if face and face in opts:
        opts = [face]
    best = None
    for f in opts:
        from_dir = OPP[f]  # direction from target toward attacker
        rel = "front" if from_dir == t["facing"] else "rear" if from_dir == OPP[t["facing"]] else "side"
        bonus, label = 0, ""
        if rel == "rear" and tags.get("rear"):
            bonus, label = 2, "rear"
        elif rel == "side" and tags.get("side"):
            bonus, label = 1, "side"
        if best is None or bonus > best[0]:
            best = (bonus, label, f, rel)
    if tags.get("pincer") and a["role"] == "blade" and _bearer_of(ctx.combat, a):
        b = _bearer_of(ctx.combat, a)
        za = _radius(ctx.combat, a)
        zt = max(1, _cheb(t["pos"], b["pos"]))
        if zt < za and za <= _max_radius(ctx, a):
            best = (best[0] + 2, (best[1] + "+pincer").strip("+"), best[2], best[3])
    return best


# ---------------------------------------------------------------- movement
def _dijkstra(ctx, c, goal):
    import heapq
    cb = ctx.combat
    start = tuple(c["pos"])
    dist = {start: 0}
    pq = [(0, start)]
    while pq:
        d, p = heapq.heappop(pq)
        if p == tuple(goal):
            return d
        if d > dist.get(p, 1e9):
            continue
        for dx, dy in DIRS.values():
            q = (p[0] + dx, p[1] + dy)
            if not _free(cb, q, c["cid"]):
                continue
            cell = _cell(cb, q)
            nd = d + (2 if cell and cell["type"] == "difficult" else 1)
            if nd < dist.get(q, 1e9):
                dist[q] = nd
                heapq.heappush(pq, (nd, q))
    return None


def _radius_changes(ctx, bearer, old_pos, forced):
    cb = ctx.combat
    out = []
    for bid in bearer.get("blade_cids", []):
        b = cb["combatants"][bid]
        if b["down"]:
            continue
        mr = _max_radius(ctx, b)
        zf = max(1, _cheb(b["pos"], old_pos))
        zt = max(1, _cheb(b["pos"], bearer["pos"]))
        if (zf if zf <= mr else mr + 1) == (zt if zt <= mr else mr + 1):
            b.pop("follow_opt", None)
            continue
        info = {"blade": bid, "from_radius": zf, "to_radius": zt}
        if forced or _status(b, "frozen"):
            info["note"] = "no choice: forced/frozen, Blade stays in its square"
            b.pop("follow_opt", None)
        elif zf > mr:
            info["note"] = "Blade was outside max radius"
        else:
            b["follow_opt"] = {"radius": zf}
            info["option"] = (f"{b['name']} may stay (now radius {zt}) or combat_move(cid='{bid}', follow=true) "
                              f"to the nearest square of radius {zf}")
        out.append(info)
    return out


def _nearest_ring(ctx, b, radius):
    cb = ctx.combat
    br = _bearer_of(cb, b)
    cands = [(x, y) for x in range(cb["map"]["width"]) for y in range(cb["map"]["height"])
             if _cheb((x, y), br["pos"]) == radius and _free(cb, (x, y), b["cid"])]
    if not cands:
        return []
    m = min(_man(b["pos"], p) for p in cands)
    return sorted(p for p in cands if _man(b["pos"], p) == m)


def combat_move(engine, cid, to=None, forced=False, by=None, force=False, follow=False):
    with engine.txn("combat_move") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        c = ctx.find(cid)
        if c["down"]:
            raise GameError(f"{c['name']} is down")
        old = list(c["pos"])
        res = {"ok": True}
        if follow:
            fo = c.get("follow_opt")
            if not fo:
                raise GameError(f"{c['name']} has no pending radius-follow option")
            cands = _nearest_ring(ctx, c, fo["radius"])
            if not cands:
                raise GameError(f"no free square in radius {fo['radius']}")
            dest = list(cands[0])
            if to is not None:
                ctx.check(tuple(_pos(to)) in cands, f"nearest square(s) of radius {fo['radius']}: {[list(p) for p in cands]}")
                dest = _pos(to)
            c["pos"] = dest
            c.pop("follow_opt", None)
            res["summary"] = f"{c['name']} follows its Bearer back to radius {fo['radius']} at {dest} (free)."
            res.update(cid=c["cid"], **{"from": old, "to": dest})
            return _finish(ctx, res)
        dest = _pos(to, "to")
        if not _in_map(cb, dest):
            raise GameError(f"{dest} is outside the map")
        if forced:
            ctx.check(_free(cb, dest, c["cid"]), f"{dest} is blocked or occupied")
            c["pos"] = dest
            chg = _radius_changes(ctx, c, old, True)
            if chg:
                res["blade_radius_change"] = chg
            res["summary"] = f"{c['name']} is moved from {old} to {dest}" + (f" by {by}" if by else "") + "."
            res.update(cid=c["cid"], **{"from": old, "to": dest})
            return _finish(ctx, res)
        _require_actor(ctx, c, None)
        if not _free(cb, dest, c["cid"]):
            raise GameError(f"{dest} is blocked or occupied" + (f" by {_occupant(cb, dest)['name']}" if _occupant(cb, dest) else ""))
        t = c["turn"]
        if _is_radius_mover(ctx, c):
            cost = _move_blade(ctx, c, dest)
            used_key = "radius_moves"
        else:
            if _status(c, "frozen"):
                ctx.check(False, f"{c['name']} is frozen and cannot move")
            cost = _dijkstra(ctx, c, dest)
            if cost is None:
                ctx.check(False, f"no path to {dest} (walls, obstacles and combatants block movement)")
                cost = _man(old, dest)
            used_key = "moved"
            ms = _move_state(ctx, c)
            if cost > ms["left"]:
                ctx.check(False, f"{dest} costs {cost} movement but only {ms['left']} left "
                                 f"(base {ms['base']}, doubled only if you do not attack; diagonal = 2)")
            cell = _cell(cb, dest)
            if cell and cell["type"] == "hazard":
                ctx.warnings.append(f"{dest} is a hazard ({cell.get('label') or cell.get('note') or 'GM decides the effect'})")
        t[used_key] += cost
        c["pos"] = dest
        if c["role"] != "blade" or not _is_radius_mover(ctx, c):
            chg = _radius_changes(ctx, c, old, False)
            if chg:
                res["blade_radius_change"] = chg
        ms = _move_state(ctx, c)
        res.update(summary=f"{c['name']} moves {old} -> {dest} (cost {cost}); {ms['left']} movement left"
                           + (" and attacking is now forbidden this turn" if ms["used"] > ms["base"] else "") + ".",
                   cid=c["cid"], **{"from": old, "to": dest}, cost=cost, movement_left=ms["left"])
        if ms["used"] > ms["base"]:
            res["attack_forbidden"] = True
        return _finish(ctx, res)


def _move_blade(ctx, c, dest):
    cb = ctx.combat
    if _status(c, "frozen"):
        ctx.check(False, f"{c['name']} is frozen: a frozen Blade cannot move at all")
    br = _bearer_of(cb, c)
    mr = _max_radius(ctx, c)
    zf, zt = _zone(ctx, c), _zone(ctx, c, dest)
    if _free_radius(c):
        if zt > mr:
            ctx.check(False, "Blade of Light allows any radius within the max radius only")
        return 0
    if zf > mr:
        cap = 2 if ctx.has_talent(c, "expeditionist") else 1
        d = _man(c["pos"], dest)
        if d > cap:
            ctx.check(False, f"outside max radius a Blade moves only {cap} square(s) per turn")
        return d
    if zt == zf:
        return 0
    if zt > mr and _cheb(dest, br["pos"]) > mr + 1:
        ctx.check(False, f"a Blade can only step one ring past max radius ({mr + 1})")
    steps = abs(zt - zf)
    if _status(br, "frozen"):
        ctx.check(False, "Bearer is frozen: the Blade is stuck in its present radius")
    ms = _move_state(ctx, c)
    if steps > ms["left"]:
        ctx.check(False, f"changing {steps} radius(es) but only {ms['left']} radius move(s) left "
                         f"(base {ms['base']}, doubled only if the Blade does not attack)")
    return steps


# ---------------------------------------------------------------- hits, reactions, effects
def _digest(ctx):
    return "; ".join(f"{c['name']} {c['hp']}/{c['max_hp']}" + ("(DOWN)" if c["down"] else "")
                     + ("[" + ",".join(s["id"] for s in c["statuses"]) + "]" if c["statuses"] else "")
                     for c in ctx.combat["combatants"].values())


def _launch(ctx, A, T, net, d):
    cb = ctx.combat
    dx, dy = DIRS[d]
    landed, terrain, first_hit, notes = list(T["pos"]), False, None, []
    for i in range(1, net + 1):
        q = [T["pos"][0] + dx * i, T["pos"][1] + dy * i]
        rem = net - (i - 1)
        if not _in_map(cb, q) or _blocks_move(cb, q):
            terrain = True
            n = _damage(ctx, T, rem, "collision")
            notes.append(f"slams into terrain after {i - 1} square(s): {n} collision damage")
            break
        o = _occupant(cb, q, T["cid"])
        if o:
            n = _damage(ctx, o, rem, "collision")
            notes.append(f"crashes through {o['name']}: {n} damage to them")
            if first_hit is None:
                first_hit = rem
            continue
        landed = q
    if first_hit:
        _damage(ctx, T, first_hit, "collision")
        notes.append(f"{T['name']} also takes {first_hit} collision damage")
    old = list(T["pos"])
    T["pos"] = landed
    if not terrain:
        cb["pending_shifts"].append({"cid": T["cid"], "delta": -1})
        notes.append("moves one place later in turn order")
    if T["blade_cids"] and old != landed:
        ctx.events.extend(f"{c['blade']} radius {c['from_radius']}->{c['to_radius']} (launched Bearer, no choice)"
                          for c in _radius_changes(ctx, T, old, True))
    return notes, landed


def _target_effect(ctx, A, T, eff, n, effect_target):
    s = None
    if eff == "burning_blade":
        s = _add_status(ctx, T, "burning", n, source=A["cid"])
    elif eff == "arts_seal":
        s = _add_status(ctx, T, "arts_seal", 1, source=A["cid"])
    elif eff == "freezing_force":
        s = _add_status(ctx, T, "frozen", 1, source=A["cid"])
    elif eff == "shadow_manipulation":
        s = _add_status(ctx, T, "shadowed", n, source=A["cid"], data={"only_target": effect_target or A["cid"]})
    elif eff == "bitter_snowstorm":
        s = _add_status(ctx, T, "snowstorm", n, source=A["cid"])
    elif eff == "blinding_eclipse":
        s = _add_status(ctx, T, "blinded", 1, source=A["cid"])
    elif eff == "electrifying_burst":
        ctx.combat["pending_shifts"].append({"cid": T["cid"], "delta": -1})
        return f"{T['name']} pushed one place later in turn order (end of turn)"
    return f"{T['name']}: {eff} ({s['remaining']} {'turn' if s['remaining'] == 1 else 'turns'})" if s else \
        f"{T['name']}: {eff} blocked"


TARGET_EFFECTS = {"burning_blade", "arts_seal", "freezing_force", "shadow_manipulation", "bitter_snowstorm",
                  "blinding_eclipse"}


def _support_effect(ctx, A, eff, n, who, art_idx=None):
    """Beneficial / chosen-ally effects, applied once. `who` = combatant."""
    if eff == "blustering_gale":
        s = _add_status(ctx, who, "blustering_gale", n, source=A["cid"])
        return f"{who['name']}: +1 defense for {s['remaining']} turns"
    if eff == "cradling_earth":
        gone = [s["id"] for s in who["statuses"] if s["id"] in ELEMENTAL_DETRIMENTAL]
        who["statuses"] = [s for s in who["statuses"] if s["id"] not in ELEMENTAL_DETRIMENTAL]
        _add_status(ctx, who, "cradled", 1, source=A["cid"])
        return f"{who['name']} cradled: cleansed {gone or 'nothing'}, immune to new detrimental effects until {A['name']}'s next turn"
    if eff == "blade_of_light":
        if who["role"] == "blade":
            _add_status(ctx, who, "blade_of_light", 1, source=A["cid"], data={"blade_free": True})
            return f"{who['name']} (Blade) moves freely among all radii next turn without penalties"
        s = _add_status(ctx, who, "blade_of_light", n, source=A["cid"], data={"range": 2})
        return f"{who['name']}: +2 attack range for {s['remaining']} turns"
    if eff == "counter_spike":
        s = _add_status(ctx, who, "counter_spike", n, source=A["cid"])
        return f"{who['name']}: counter spike for {s['remaining']} turns"
    if eff == "electrifying_burst":
        ctx.combat["pending_shifts"].append({"cid": who["cid"], "delta": 1})
        return f"{who['name']} moves one place sooner in turn order (end of turn)"
    if eff == "invigorating_steam":
        if who["kind"] != "pc":
            return f"{who['name']}: invigorating steam (NPC: grant one advantaged attack/defense, GM tracks)"
        i = 0 if art_idx is None else int(art_idx)
        while len(who["cooldowns"]) <= i:
            who["cooldowns"].append(0)
        if who["cooldowns"][i] > 0:
            who["cooldowns"][i] -= 1
            return f"{who['name']}: art {i} cooldown reduced to {who['cooldowns'][i]}"
        who.setdefault("steam", {})[str(i)] = who.get("steam", {}).get(str(i), 0) + 1
        return f"{who['name']}: art {i} is ready; its next cooldown starts 1 lower"
    return ""


def _hit_target(ctx, A, T, net, tags, face_dir, bonus_dmg=0, effect=None, effect_target=None, dmg=None):
    r = {"cid": T["cid"], "name": T["name"], "net": net}
    dealt = _damage(ctx, T, (net if dmg is None else dmg) + bonus_dmg, f"{A['name']}'s attack")
    r["damage"] = dealt
    notes = []
    if dealt and _status(T, "counter_spike") and T is not A:
        d = _damage(ctx, A, 1, "counter spike")
        notes.append(f"counter spike: {A['name']} takes {d}")
    if not T["down"]:
        if tags.get("break"):
            _add_status(ctx, T, "broken", 1, source=A["cid"])
            notes.append("broken")
        if tags.get("topple"):
            if _remove_status(T, "broken"):
                _add_status(ctx, T, "toppled", 1, "own_turns", A["cid"])
                notes.append("toppled")
            else:
                notes.append("topple fizzles (target not broken)")
        if tags.get("launch"):
            if _remove_status(T, "broken"):
                n2, landed = _launch(ctx, A, T, max(net, 1), face_dir)
                notes.append(f"launched {net} to {landed}: " + "; ".join(n2))
            else:
                notes.append("launch fizzles (target not broken)")
        if tags.get("stagger"):
            ctx.combat["pending_shifts"].append({"cid": T["cid"], "delta": -1})
            notes.append("staggered (one place later at end of turn)")
        if effect in TARGET_EFFECTS or (effect == "electrifying_burst" and not effect_target):
            if not T["down"]:
                notes.append(_target_effect(ctx, A, T, effect, max(net, 1), effect_target))
    r["hp"] = f"{T['hp']}/{T['max_hp']}"
    r["down"] = T["down"]
    if notes:
        r["notes"] = notes
    return r


def _resolve_effect(ctx, A, tags, effect):
    ch = ctx.char(A)
    aff = set(ch.get("affinities", [])) if ch else set()
    allowed = set()
    if tags.get("unique_effect"):
        allowed |= {e for e, el in UNIQUE_EFFECTS.items() if el in aff}
    shared = [e for e in SHARED_EFFECTS if tags.get(e)]
    for e in shared:
        if any(ELEMENT_IDEA[a] == SHARED_EFFECTS[e] for a in aff):
            allowed.add(e)
    if effect in (None, ""):
        if not tags.get("unique_effect") and len(shared) == 1:
            effect = shared[0]
        elif tags.get("unique_effect") or shared:
            ctx.check(False, f"this art has elemental effect(s) {sorted(allowed) or shared}; pass effect=<id> or effect='none'")
            return None
        else:
            return None
    if effect == "none":
        return None
    if effect not in ALL_EFFECTS:
        raise GameError(f"unknown effect {effect!r}; valid: {', '.join(ALL_EFFECTS)}")
    ctx.check(effect in allowed, f"effect {effect} not available on this art with {A['name']}'s affinities "
                                 f"(allowed: {sorted(allowed) or 'none'})")
    return effect


# ---------------------------------------------------------------- area shapes
def _area(ctx, A, tags, at, direction, target, rng, shape_hint=None):
    """returns (targets list, desc, facing)."""
    cb = ctx.combat
    circle = tags.get("circle", 0) or (1 if shape_hint == "circle" else 0)
    line = tags.get("line", 0) or (1 if shape_hint == "line" else 0)
    if circle:
        if at is None and target is not None:
            at = ctx.find(target)["pos"]
        if at is None:
            ctx.check(rng == 0, "circle attack needs at=[x,y] (centre)")
            at = list(A["pos"])
        at = _pos(at, "at")
        ctx.check(_man(A["pos"], at) <= rng, f"circle centre {at} is {_man(A['pos'], at)} away; range {rng}")
        ctx.check(_in_map(cb, at), "centre outside map")
        ctx.check(at == A["pos"] or _los(cb, A["pos"], at), "no line of sight to the centre")
        hit = [c for c in cb["combatants"].values() if not c["down"] and c is not A
               and _cheb(c["pos"], at) <= circle and _los(cb, at, c["pos"])]
        f = _facing_options(A, {"pos": at})[0] if at != A["pos"] else A["facing"]
        return hit, f"circle {2 * circle + 1}x{2 * circle + 1} at {at}", f
    d = direction
    if d is None:
        ref = ctx.find(target)["pos"] if target is not None else at
        if ref is None:
            raise GameError("line attack needs direction N/E/S/W (or an aligned target/at)")
        dx, dy = ref[0] - A["pos"][0], ref[1] - A["pos"][1]
        if dx and dy:
            raise GameError("line attacks go in a cardinal direction; target is not aligned")
        d = "E" if dx > 0 else "W" if dx < 0 else "S" if dy > 0 else "N"
    d = str(d).upper()
    if d not in DIRS:
        raise GameError("direction must be N, E, S or W")
    length = 5 + tags.get("range", 0) if tags.get("line") else 5 + rng
    hit = []
    for i in range(1, length + 1):
        q = [A["pos"][0] + DIRS[d][0] * i, A["pos"][1] + DIRS[d][1] * i]
        if not _in_map(cb, q) or _blocks_sight(cb, q):
            break
        o = _occupant(cb, q)
        if o:
            hit.append(o)
    return hit, f"line {length} {d}", d


def _def_value(T, level):
    d = T["card"]["defense"]
    if isinstance(level, int):
        return level
    if level not in d:
        raise GameError("defense must be normal, adv, dis or an integer")
    return d[level]


def _intercept(ctx, T, A):
    """Negate positional: T's Blade steps between T and attacker A. Returns note or None."""
    cb = ctx.combat
    ar = max(1, _cheb(A["pos"], T["pos"]))
    for bid in T["blade_cids"]:
        b = cb["combatants"][bid]
        if b["down"]:
            continue
        br = max(1, _cheb(b["pos"], T["pos"]))
        if br > ar:
            continue
        if ar == 1:
            cands = [(A["pos"][0] + dx, A["pos"][1] + dy) for dx, dy in DIRS.values()]
        else:
            cands = _line_cells(T["pos"], A["pos"])[1:-1]
        cands = [p for p in cands if _free(cb, p, b["cid"])]
        if not cands:
            return f"{b['name']} intercepts (no free square to move into)"
        p = min(cands, key=lambda q: (_man(q, b["pos"]), q))
        b["pos"] = list(p)
        return f"{b['name']} intercepts and moves to {list(p)}"
    ctx.check(False, f"{T['name']} has no Blade in the same or a lower radius than the attacker to negate the positional bonus")
    return None


def combat_attack(engine, attacker, kind="basic", art=None, target=None, at=None, direction=None, attribute=None,
                  label="", modifier=0, modifier_notes="", defense="normal", effect=None, effect_target=None,
                  heal_target=None, negate_positional=False, spare=None, defender_attributes=None,
                  defender_modifiers=None, effect_art=None, face=None, force=False):
    with engine.txn("combat_attack") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        A = ctx.find(attacker)
        _require_actor(ctx, A, True)
        if A["kind"] != "pc":
            raise GameError(f"{A['name']} is an NPC; use combat_npc_attack (NPCs never roll)")
        ch = ctx.char(A)
        if art is not None:
            kind = "art"
        if kind not in ("basic", "art"):
            raise GameError("kind must be 'basic' or 'art'")
        if not attribute:
            raise GameError("attribute is required (the attribute that fits the narration)")
        an, av = ctx.attr(A, attribute)
        sh = _status(A, "shadowed")
        tags, art_obj, art_i = {}, None, None
        if kind == "art":
            if art is None:
                raise GameError("art index required for kind='art'")
            art_i = int(art)
            if not 0 <= art_i < len(ch.get("arts", [])):
                raise GameError(f"art index must be 0..{len(ch.get('arts', [])) - 1}")
            art_obj = ch["arts"][art_i]
            tags = dict(art_obj.get("tags", {}))
            ctx.check(not _status(A, "arts_seal"), f"{A['name']}'s arts are sealed this turn")
            cd = A["cooldowns"][art_i] if art_i < len(A["cooldowns"]) else 0
            ctx.check(cd == 0, f"art {art_i} '{art_obj['name']}' is on cooldown ({cd})")
        defender_attributes = defender_attributes or {}
        defender_modifiers = defender_modifiers or {}
        spare = [ctx.find(s)["cid"] for s in (spare or [])]
        if spare:
            ctx.check(bool(tags.get("precise")), "only arts with the precise tag may spare targets")
        rng = _range_of(ctx, A, tags, kind == "basic")
        aoe = bool(tags.get("circle") or tags.get("line"))
        pos_bonus, pos_label, pos_note = 0, "", None
        if aoe:
            targets, desc, fdir = _area(ctx, A, tags, at, direction, target, rng)
            targets = [t for t in targets if t["cid"] not in spare]
            if not targets:
                ctx.warnings.append("the area catches no one")
        else:
            if target is None and at is not None:
                target = (_occupant(cb, _pos(at)) or {}).get("cid")
            if target is None:
                raise GameError("target (cid) required")
            T = ctx.find(target)
            ctx.check(not T["down"], f"{T['name']} is down")
            ctx.check(T is not A, "cannot attack yourself")
            ctx.check(not ctx.allies(A, T), f"{T['name']} is an ally")
            d = _man(A["pos"], T["pos"])
            ctx.check(d <= rng, f"{T['name']} is {d} squares away; range is {rng}")
            ctx.check(_los(cb, A["pos"], T["pos"]), f"no line of sight to {T['name']}")
            if face is not None:
                face = str(face).upper()
                if face not in _facing_options(A, T):
                    raise GameError(f"face must be one of {_facing_options(A, T)}")
            pos_bonus, pos_label, fdir, rel = _positional(ctx, A, T, tags, face)
            if negate_positional:
                if pos_bonus:
                    pos_note = _intercept(ctx, T, A)
                    pos_bonus, pos_label = 0, ""
                else:
                    ctx.warnings.append("negate_positional: there was no positional bonus to negate")
            elif pos_bonus and T["blade_cids"]:
                ctx.warnings.append(f"{T['name']}'s Blade could negate the positional bonus (negate_positional=true)")
            targets, desc = [T], ""
        if sh and sh["data"].get("only_target"):
            ctx.check(all(t["cid"] == sh["data"]["only_target"] for t in targets) and targets,
                      f"{A['name']} is shadowed: may only attack {sh['data']['only_target']}")
        eff = _resolve_effect(ctx, A, tags, effect) if kind == "art" else None
        # --- attacker roll
        A["facing"] = fdir
        mods, half = _attack_mods(ctx, A)
        if tags.get("potency"):
            mods.insert(0, ("potency", tags["potency"]))
        if pos_bonus:
            mods.append((pos_label, pos_bonus))
        if modifier:
            mods.append((modifier_notes or "modifier", int(modifier)))
        r = _do_roll(ctx, A, label or (art_obj["name"] if art_obj else "basic attack"), "attack", an, av, mods, half)
        res_t, recs, total_dmg, best, any_hit = [], [], 0, None, False
        special_gain = None
        for T in targets:
            tr = {}
            if T["kind"] == "pc":
                if T["cid"] not in defender_attributes:
                    raise GameError(f"defender_attributes[{T['cid']!r}] required: the attribute {T['name']} defends with")
                dn, dv = ctx.attr(T, defender_attributes[T["cid"]])
                dm, dh = _defense_mods(ctx, T)
                if defender_modifiers.get(T["cid"]):
                    dm.append(("modifier", int(defender_modifiers[T["cid"]])))
                dr = _do_roll(ctx, T, f"defend vs {A['name']}", "defense", dn, dv, dm, dh)
                check = dr["successes"]
                tr["defense_roll"] = _pool_text(dr)
                dnet = dr["successes"] - r["successes"]
                _record(ctx, dr, r["successes"], dnet, note=f"defends against {A['name']}")
            else:
                lvl = defense.get(T["cid"], "normal") if isinstance(defense, dict) else defense
                check = max(0, _def_value(T, lvl) + (1 if _status(T, "blustering_gale") else 0)
                            - (1 if _status(T, "blinded") else 0))
            net = r["successes"] - check
            auto = None
            if net < 1 and _status(T, "toppled"):
                net, auto = 1, "topple"
                tr["note"] = "toppled target: failed attack becomes a near hit"
            tr.update(cid=T["cid"], check=check, net=net, tier=_tier(net))
            if best is None or net > best[0]:
                best = (net, check, auto)
            if net >= 1:
                any_hit = True
                bonus = 1 if (ctx.has_talent(A, "dirty_fighter") and _status(T, "toppled")
                              and _man(A["pos"], T["pos"]) <= 1) else 0
                hr = _hit_target(ctx, A, T, net, tags, fdir, bonus, eff,
                                 ctx.find(effect_target)["cid"] if effect_target else None)
                tr.update(hr)
                total_dmg += hr["damage"]
            else:
                tr["damage"] = 0
                tr["hp"] = f"{T['hp']}/{T['max_hp']}"
            T_after = T
            res_t.append(tr)
        # support effects / healing (once, only if the attack hit)
        support = []
        nets = [t["net"] for t in res_t if t["net"] >= 1]
        if any_hit and eff and (eff not in TARGET_EFFECTS and not (eff == "electrifying_burst" and not effect_target)):
            who = ctx.find(effect_target) if effect_target else A
            support.append(_support_effect(ctx, A, eff, max(nets), who, effect_art))
        if any_hit and tags.get("healing_potion"):
            hw = ctx.find(heal_target) if heal_target else A
            got = _heal(ctx, hw, max(nets))
            support.append(f"{hw['name']} healed {got} (potion)")
        if total_dmg and not A["turn"]["dealt_damage"]:
            A["turn"]["dealt_damage"] = True
            old, new = _add_special(ctx, ctx.team_of(A), 1)
            special_gain = f"team special {old}->{new}"
        for T in targets:
            if not T["down"] and T is not A and not aoe:
                T["facing"] = OPP[fdir]
        A["turn"]["acted"] = A["turn"]["attacked"] = True
        if kind == "art":
            steam = A.get("steam", {}).get(str(art_i), 0)
            if steam:
                A["steam"][str(art_i)] = 0
            while len(A["cooldowns"]) <= art_i:
                A["cooldowns"].append(0)
            A["cooldowns"][art_i] = max(1, 6 - tags.get("cooldown", 0) - steam)
        if tags.get("rush") and any_hit:
            A["turn"]["bonus_move"] += tags["rush"]
        # records
        note = pos_note or ""
        bnet, bcheck, bauto = best if best else (0, 0, None)
        rec = _record(ctx, r, bcheck, bnet, total_dmg, bauto,
                      note=(note + " " if note else "") + ("; ".join(f"{t['cid']}:net {t['net']}" for t in res_t) if aoe else ""))
        # summary
        parts = []
        for t in res_t:
            nm = ctx.find(t["cid"])["name"]
            dtxt = f"{t['damage']} damage" if t["damage"] else "no damage"
            extra = ("; " + "; ".join(t["notes"])) if t.get("notes") else ""
            how = "defense " + str(t["check"]) if ctx.find(t["cid"])["kind"] == "npc" else \
                f"{nm}'s defense roll ({t['check']} successes)"
            parts.append(f"vs {nm} {how}: {TIER_TEXT[t['tier']]}, {dtxt}{extra}")
        summary = f"{A['name']} ({_pool_text(r)}) " + ("; ".join(parts) if parts else "hits nothing")
        if pos_note:
            summary += f"; {pos_note}"
        if support:
            summary += "; " + "; ".join(support)
        summary += (f"; {special_gain}" if special_gain else "") + "."
        out = {"ok": True, "summary": summary, "attacker": A["cid"], "kind": kind, "targets": res_t,
               "roll": rec["id"] if isinstance(rec, dict) else None, "dice": r["dice"]}
        if aoe:
            out["area"] = desc
        if support:
            out["support"] = support
        if A["down"] or (cb["order"] and ctx.current is A and False):
            pass
        ms = _move_state(ctx, A)
        out["actor_state"] = {"action_used": True, "movement_left": ms["left"]}
        out["digest"] = _digest(ctx)
        _auto_advance(ctx, out)
        return _finish(ctx, out)


def _auto_advance(ctx, out):
    """If the current actor went down mid-turn (counter spike, collision...), start the next turn."""
    cb = ctx.combat
    if cb["order"] and not cb["pending"]:
        first = cb["combatants"][cb["order"][0]]
        if first.get("start_applied") is False or first["down"]:
            nxt = _advance(ctx)
            if nxt:
                out["turn_passed_to"] = nxt["cid"]
                out["next_turn"] = _context(ctx, nxt)


# ---------------------------------------------------------------- NPC attacks
def _tagdict(tags):
    out = {}
    if isinstance(tags, dict):
        return {k: int(v) for k, v in tags.items()}
    for t in tags or []:
        out[t] = out.get(t, 0) + 1
    return out


def combat_npc_attack(engine, attacker, targets=None, level="normal", defender_attributes=None,
                      defender_modifiers=None, tags=None, effect=None, effect_target=None, label="",
                      ignore_range=False, at=None, direction=None, shape=None, defense="normal", spare=None,
                      face=None, force=False):
    with engine.txn("combat_npc_attack") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        A = ctx.find(attacker)
        _require_actor(ctx, A, True)
        if A["kind"] != "npc":
            raise GameError(f"{A['name']} is a PC; use combat_attack (PCs roll)")
        card = A["card"]
        tg = _tagdict(tags)
        if tg and _status(A, "arts_seal"):
            ctx.warnings.append("arts sealed: art tags ignored")
            tg = {}
        unknown = [t for t in tg if t not in card["art_tags"] and t not in ("circle", "line", "range")]
        if unknown:
            ctx.warnings.append(f"tags {unknown} are not on {A['name']}'s card art_tags")
        base = level if isinstance(level, int) else card["attack"].get(level)
        if base is None:
            raise GameError("level must be normal, adv, dis or an integer")
        value = max(0, base - (1 if _status(A, "blinded") else 0))
        defender_attributes = defender_attributes or {}
        defender_modifiers = defender_modifiers or {}
        spare = [ctx.find(s)["cid"] for s in (spare or [])]
        rng = int(card.get("range", 1)) + tg.get("range", 0)
        aoe = bool(shape or tg.get("circle") or tg.get("line"))
        if aoe:
            hint = shape if shape in ("circle", "line") else None
            arng = 99 if ignore_range else tg.get("range", 0)
            T_list, desc, fdir = _area(ctx, A, tg, at, direction, targets[0] if targets else None, arng, hint)
            T_list = [t for t in T_list if t["cid"] not in spare]
        else:
            if not targets:
                raise GameError("targets (list of cids) required")
            T_list = [ctx.find(t) for t in targets]
            fdir = None
            for T in T_list:
                ctx.check(not T["down"], f"{T['name']} is down")
                d = _man(A["pos"], T["pos"])
                ctx.check(ignore_range or d <= rng, f"{T['name']} is {d} away; {A['name']}'s range is {rng} (ignore_range=true to override)")
                ctx.check(_los(cb, A["pos"], T["pos"]), f"no line of sight to {T['name']}")
            fdir = _facing_options(A, T_list[0])[0] if face is None else str(face).upper()
        sh = _status(A, "shadowed")
        if sh and sh["data"].get("only_target"):
            ctx.check(T_list and all(t["cid"] == sh["data"]["only_target"] for t in T_list),
                      f"{A['name']} is shadowed: may only attack {sh['data']['only_target']}")
        A["facing"] = fdir
        eff = None
        if effect and effect != "none":
            if effect not in ALL_EFFECTS:
                raise GameError(f"unknown effect {effect!r}")
            eff = effect
        res_t, total, any_hit, parts = [], 0, False, []
        nets = []
        for T in T_list:
            tr = {"cid": T["cid"]}
            if T["kind"] == "pc":
                if T["cid"] not in defender_attributes:
                    raise GameError(f"defender_attributes[{T['cid']!r}] required: the attribute {T['name']} defends with")
                dn, dv = ctx.attr(T, defender_attributes[T["cid"]])
                dm, dh = _defense_mods(ctx, T)
                if defender_modifiers.get(T["cid"]):
                    dm.append(("modifier", int(defender_modifiers[T["cid"]])))
                dr = _do_roll(ctx, T, f"defend vs {A['name']}", "defense", dn, dv, dm, dh)
                s = dr["successes"]
                dmg = max(0, value - s)
                tr["defense_roll"] = _pool_text(dr)
            else:
                dmg = max(0, value - max(0, _def_value(T, defense.get(T["cid"], "normal") if isinstance(defense, dict) else defense)))
                s = None
            net = dmg
            auto = None
            if net < 1 and _status(T, "toppled"):
                net, auto, dmg = 1, "topple", 1
            if T["kind"] == "pc":
                _record(ctx, dr, value, dr["successes"] - value, damage=dmg, auto=auto,
                        note=f"defends against {A['name']}'s attack value {value}")
            tr.update(attack_value=value, net=net, tier=_tier(net))
            if net >= 1:
                any_hit = True
                nets.append(net)
                tr.update(_hit_target(ctx, A, T, net, tg, fdir or "S", 0, eff if eff in TARGET_EFFECTS or (eff == "electrifying_burst" and not effect_target) else None,
                                      ctx.find(effect_target)["cid"] if effect_target else None, dmg=dmg))
                total += tr["damage"]
            else:
                tr["damage"] = 0
                tr["hp"] = f"{T['hp']}/{T['max_hp']}"
            res_t.append(tr)
            if tg.get("rush") and any_hit:
                pass
            if not T["down"] and not aoe:
                T["facing"] = OPP[fdir]
            who = "defense roll " + str(s) if s is not None else "static defense"
            parts.append(f"vs {T['name']} ({who}): {TIER_TEXT[tr['tier']]}, {tr['damage']} damage"
                         + (("; " + "; ".join(tr["notes"])) if tr.get("notes") else ""))
        support = []
        if any_hit and eff and not (eff in TARGET_EFFECTS or (eff == "electrifying_burst" and not effect_target)):
            support.append(_support_effect(ctx, A, eff, max(nets), ctx.find(effect_target) if effect_target else A))
        if tg.get("rush") and any_hit:
            A["turn"]["bonus_move"] += tg["rush"]
        A["turn"]["acted"] = A["turn"]["attacked"] = True
        summary = f"{A['name']} attacks (value {value}) " + "; ".join(parts or ["hits nothing"])
        if support:
            summary += "; " + "; ".join(support)
        out = {"ok": True, "summary": summary + ".", "attacker": A["cid"], "attack_value": value,
               "targets": res_t, "digest": _digest(ctx)}
        if support:
            out["support"] = support
        _auto_advance(ctx, out)
        return _finish(ctx, out)


# ---------------------------------------------------------------- specials
def _apply_special(ctx, A, alloc, total, eff, effect_target, effect_art):
    out, notes = [], []
    for cid, dmg in alloc.items():
        T = ctx.find(cid)
        d = _damage(ctx, T, dmg, f"{A['name']}'s special")
        row = {"cid": T["cid"], "damage": d, "hp": f"{T['hp']}/{T['max_hp']}", "down": T["down"]}
        if eff and not T["down"] and (eff in TARGET_EFFECTS or (eff == "electrifying_burst" and not effect_target)) and dmg > 0:
            row["effect"] = _target_effect(ctx, A, T, eff, dmg, effect_target)
        out.append(row)
    if eff and not (eff in TARGET_EFFECTS or (eff == "electrifying_burst" and not effect_target)):
        who = ctx.find(effect_target) if effect_target else A
        notes.append(_support_effect(ctx, A, eff, total, who, effect_art))
    return out, notes


def combat_special(engine, attacker, level=0, ideas=None, effect=None, target=None, at=None, label="",
                   free_burst=False, allocations=None, partner=None, effect_target=None, effect_art=None,
                   modifier=0, force=False):
    with engine.txn("combat_special") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        A = ctx.find(attacker)
        _require_actor(ctx, A, True)
        if A["kind"] != "pc":
            raise GameError("only player characters use special attacks")
        sp = cb["special"]
        team = ctx.team_of(A)
        P = ctx.find(partner) if partner else None
        pair = None
        if free_burst:
            if P is None:
                raise GameError("free_burst needs partner=<cid of the character you reconcile with>")
            pair = pair_key(A["char_id"], P["char_id"])
            val = int(st["affinity"].get(pair, 0))
            if val >= 0:
                raise GameError(f"{A['name']} and {P['name']} have affinity {val}: a reconciliation burst needs negative affinity")
            lvl = 3 if val <= -2 else 1
            ctx.check(level in (0, lvl), f"affinity {val} allows a free level {lvl} burst")
            level = lvl
        else:
            if level not in (1, 2, 3):
                raise GameError("level must be 1, 2 or 3")
            need_lvl = sp["chain_level"] + 1
            ctx.check(level == need_lvl, f"the next special must be level {need_lvl} (chain is at {sp['chain_level']})")
            ctx.check(sp["points"].get(team, 0) >= 6 * level,
                      f"level {level} needs {6 * level} special points; team has {sp['points'].get(team, 0)}")
        if level >= 2 and P is None:
            cands = [cb["combatants"][b] for b in A["blade_cids"]] if A["role"] == "bearer" else \
                [_bearer_of(cb, A)]
            cands = [c for c in cands if c and not c["down"]]
            if cands:
                P = cands[0]
        if level >= 2 and (P is None or P["down"]):
            ctx.check(False, f"level {level} specials need a partner who is still up")
            P = None
        ideas = ideas or {}
        ia = ideas.get(A["cid"]) or ideas.get("attacker")
        if ia not in IDEAS:
            raise GameError(f"ideas must name {A['name']}'s idea: one of {', '.join(IDEAS)}")
        ip = None
        if level >= 2 and P:
            ip = ideas.get(P["cid"]) or ideas.get("partner") or ia
            if ip not in IDEAS:
                raise GameError("unknown partner idea")
            if level == 2:
                ctx.check(ip == ia, "a level 2 special: attacker and partner roll the same idea")
        if free_burst and level == 1:
            sa = sum(ctx.char(A)["attributes"].get(x, 1) for x in IDEAS[ia])
            sb = sum(ctx.char(P)["attributes"].get(x, 1) for x in IDEAS[ia])
            ctx.check(sa >= sb, f"{P['name']} has the higher total in {ia}; they should perform it")
        used_ideas = {ia} | ({ip} if ip else set())
        allowed = {e for e, el in UNIQUE_EFFECTS.items() if ELEMENT_IDEA[el] in used_ideas} | \
                  {e for e, i in SHARED_EFFECTS.items() if i in used_ideas}
        eff = None if effect in (None, "none", "") else effect
        if eff:
            if eff not in ALL_EFFECTS:
                raise GameError(f"unknown effect {eff!r}")
            ctx.check(eff in allowed, f"{eff} does not belong to the idea(s) {sorted(used_ideas)}; allowed: {sorted(allowed)}")
        # targets
        area = None
        if level == 1:
            if target is None:
                raise GameError("level 1 special needs target=<cid>")
            T = ctx.find(target)
            ctx.check(not T["down"], f"{T['name']} is down")
            ctx.check(_los(cb, A["pos"], T["pos"]), f"no line of sight to {T['name']}")
            cands = [T]
        else:
            rad = level - 1
            ctr = _pos(at) if at is not None else (ctx.find(target)["pos"] if target is not None else None)
            if ctr is None:
                raise GameError(f"level {level} special needs at=[x,y] (centre of the {2 * rad + 1}x{2 * rad + 1} area) or a target")
            ctx.check(_los(cb, A["pos"], ctr) or ctr == A["pos"], "no line of sight to the centre")
            cands = [c for c in cb["combatants"].values() if not c["down"] and _cheb(c["pos"], ctr) <= rad
                     and c is not A]
            area = f"{2 * rad + 1}x{2 * rad + 1} at {ctr}"
        # rolls
        rollers = [(A, ia)] + ([(P, ip)] if ip else [])
        rolls, total, texts = [], 0, []
        for who, idea in rollers:
            attrs = IDEAS[idea]
            base = sum(ctx.char(who)["attributes"].get(x, 1) for x in attrs)
            mods, half = _attack_mods(ctx, who)
            if who is A and modifier:
                mods.append(("modifier", int(modifier)))
            r = _do_roll(ctx, who, label or f"level {level} special ({idea})", "special", idea, base, mods, half)
            texts.append(f"{who['name']} {_pool_text(r)}")
            r["attribute"] = list(attrs)
            rolls.append(r)
            total += r["successes"]
        # spend
        if not free_burst:
            n_teams = len(sp["points"])
            if n_teams == 1:
                if level == 3:
                    sp["points"][team] = max(0, sp["points"][team] - 18)
            else:
                sp["points"][team] -= 6 * level
                if n_teams == 2 and level == 2:
                    other = next(t for t in sp["points"] if t != team)
                    _add_special(ctx, other, 6)
                    ctx.ev(f"team {other} gains 6 special points (two-team rule)")
            sp["chain_level"] = level if level < 3 else 0
        else:
            st["affinity"][pair] = 0
            ctx.ev(f"{A['name']} and {P['name']} reconcile: affinity reset to 0")
        A["turn"]["acted"] = A["turn"]["attacked"] = True
        for r in rolls:
            _record(ctx, r, 0, total if r is rolls[0] else r["successes"], damage=total if r is rolls[0] else None,
                    auto="undodgeable", note=f"special total {total}")
        if level == 1:
            alloc = {cands[0]["cid"]: total}
            A["facing"] = _facing_options(A, cands[0])[0]
        else:
            enemies = [c for c in cands if not ctx.allies(A, c)]
            if allocations:
                alloc = {ctx.find(k)["cid"]: int(v) for k, v in allocations.items()}
                bad = [k for k in alloc if k not in [c["cid"] for c in cands]]
                ctx.check(not bad, f"{bad} are not inside the area")
                ctx.check(sum(alloc.values()) == total, f"allocations total {sum(alloc.values())} but the special deals {total}")
            elif len(enemies) == 1:
                alloc = {enemies[0]["cid"]: total}
            elif not enemies:
                ctx.check(False, "no enemies in the area")
                alloc = {}
            else:
                cb["pending"] = {"type": "special_split", "attacker": A["cid"], "total": total, "effect": eff,
                                 "effect_target": effect_target, "effect_art": effect_art, "level": level,
                                 "candidates": [c["cid"] for c in cands]}
                return _finish(ctx, {"ok": True, "summary": f"{A['name']}'s level {level} special: " + "; ".join(texts)
                                     + f"; {total} damage to divide among {[c['cid'] for c in enemies]} "
                                       "-> call combat_special_assign(allocations={cid: damage}).",
                                     "total": total, "area": area, "candidates": [c["cid"] for c in cands]})
        rows, notes = _apply_special(ctx, A, alloc, total, eff, effect_target, effect_art)
        summary = (f"{A['name']}'s level {level} special{' (free reconciliation burst)' if free_burst else ''}: "
                   + "; ".join(texts) + f"; {total} damage"
                   + "".join(f" to {ctx.find(r['cid'])['name']} ({r['damage']}, hp {r['hp']})" for r in rows)
                   + ("; " + "; ".join(r["effect"] for r in rows if r.get("effect")) if any(r.get("effect") for r in rows) else "")
                   + ("; " + "; ".join(notes) if notes else "")
                   + f". Chain level now {sp['chain_level']}.")
        out = {"ok": True, "summary": summary, "level": level, "total": total, "targets": rows,
               "chain_level": sp["chain_level"], "digest": _digest(ctx)}
        _auto_advance(ctx, out)
        return _finish(ctx, out)


def combat_special_assign(engine, allocations, force=False):
    with engine.txn("combat_special_assign") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        p = cb["pending"]
        if not p or p.get("type") != "special_split":
            raise GameError("no special_split pending")
        A = ctx.find(p["attacker"])
        alloc = {ctx.find(k)["cid"]: int(v) for k, v in (allocations or {}).items()}
        bad = [k for k in alloc if k not in p["candidates"]]
        ctx.check(not bad, f"{bad} are not inside the special's area")
        ctx.check(sum(alloc.values()) == p["total"], f"allocations total {sum(alloc.values())}; must equal {p['total']}")
        cb["pending"] = None
        rows, notes = _apply_special(ctx, A, alloc, p["total"], p["effect"], p["effect_target"], p["effect_art"])
        summary = (f"{A['name']}'s special damage split: "
                   + "; ".join(f"{ctx.find(r['cid'])['name']} {r['damage']} (hp {r['hp']})" + (f", {r['effect']}" if r.get("effect") else "") for r in rows)
                   + ("; " + "; ".join(notes) if notes else "") + ".")
        out = {"ok": True, "summary": summary, "targets": rows, "digest": _digest(ctx)}
        _auto_advance(ctx, out)
        return _finish(ctx, out)


# ---------------------------------------------------------------- actions, turns
def combat_action(engine, cid, label, attribute=None, check=0, modifier=0, kind="other", target=None,
                  offensive=False, art=None, reset_art=None, force=False):
    with engine.txn("combat_action") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        A = ctx.find(cid)
        if kind not in ("other", "help_up", "defend", "heal"):
            raise GameError("kind must be other, help_up, defend or heal")
        _require_actor(ctx, A, True, offensive=bool(offensive or kind == "heal" and False))
        out = {"ok": True}
        if kind == "help_up":
            if target is None:
                raise GameError("help_up needs target (adjacent toppled ally)")
            T = ctx.find(target)
            ctx.check(_man(A["pos"], T["pos"]) == 1, f"{T['name']} is not adjacent")
            ctx.check(bool(_status(T, "toppled")), f"{T['name']} is not toppled")
            _remove_status(T, "toppled")
            A["turn"]["acted"] = True
            out["summary"] = f"{A['name']} helps {T['name']} up: toppled removed."
            return _finish(ctx, out)
        r = None
        if attribute:
            an, av = ctx.attr(A, attribute)
            mods, half = _attack_mods(ctx, A)
            if kind == "heal" and art is not None:
                mods.insert(0, ("potency", ctx.char(A)["arts"][int(art)].get("tags", {}).get("potency", 0)))
            if modifier:
                mods.append(("modifier", int(modifier)))
            r = _do_roll(ctx, A, label, "check", an, av, mods, half)
        if kind == "defend":
            _add_status(ctx, A, "guarding", 1, source=A["cid"])
            A["turn"]["acted"] = True
            out["summary"] = f"{A['name']} takes a defensive stance ({label}); GM applies any defense bonus via defender_modifiers."
            if r:
                rec = _record(ctx, r, check, r["successes"] - check)
                out["summary"] += f" Roll: {_pool_text(r)}."
            return _finish(ctx, out)
        if kind == "heal":
            ctx.check(ctx.has_talent(A, "healer"), f"{A['name']} lacks the Healer talent")
            if art is None or r is None:
                raise GameError("heal needs art=<index> and attribute")
            art_i = int(art)
            tags = ctx.char(A)["arts"][art_i].get("tags", {})
            ctx.check(not _status(A, "arts_seal"), "arts are sealed")
            ctx.check((A["cooldowns"][art_i] if art_i < len(A["cooldowns"]) else 0) == 0, f"art {art_i} is on cooldown")
            used = [x for x in A["combat_talents_used"] if x.startswith("healer_art:")]
            ctx.check(not used or used[0] == f"healer_art:{art_i}", "Healer can only use the same art for the rest of this combat")
            if not used:
                A["combat_talents_used"].append(f"healer_art:{art_i}")
            targets = target if isinstance(target, list) else [target or A["cid"]]
            healed = []
            for t in targets:
                T = ctx.find(t)
                healed.append(f"{T['name']} +{_heal(ctx, T, r['successes'])}")
            A["cooldowns"][art_i] = max(1, 6 - tags.get("cooldown", 0))
            others = [i for i in range(len(A["cooldowns"])) if i != art_i]
            ready = [i for i in others if A["cooldowns"][i] == 0]
            extra = ""
            if reset_art is not None:
                ri = int(reset_art)
            elif ready:
                ri = ready[0]
            else:
                running = [i for i in others if A["cooldowns"][i] > 0]
                ri = min(running, key=lambda i: A["cooldowns"][i]) if running else None
            if ri is not None:
                ct = ctx.char(A)["arts"][ri].get("tags", {}).get("cooldown", 0)
                A["cooldowns"][ri] = max(1, 6 - ct)
                extra = f"; art {ri} cooldown reset to {A['cooldowns'][ri]} (Healer cost)"
            A["turn"]["acted"] = True
            _record(ctx, r, check, r["successes"] - check, note="healer")
            out["summary"] = f"{A['name']} heals ({_pool_text(r)}): {', '.join(healed)}{extra}."
            return _finish(ctx, out)
        A["turn"]["acted"] = True
        if offensive:
            A["turn"]["attacked"] = True
        if r:
            net = r["successes"] - check
            _record(ctx, r, check, net)
            out["summary"] = f"{A['name']} {label}: {_pool_text(r)} vs check {check}: net {net} ({TIER_TEXT[_tier(net)]})."
            out["tier"] = _tier(net)
        else:
            out["summary"] = f"{A['name']} uses their action: {label}."
        return _finish(ctx, out)


def combat_end_turn(engine, cid=None, facing=None, blade_pos=None, force=False):
    with engine.txn("combat_end_turn") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        ctx.check(not cb["pending"], _pending_error(cb) if cb["pending"] else "")
        A = ctx.find(cid) if cid else ctx.current
        if A is None:
            raise GameError("nobody is left in the turn order")
        was_current = ctx.current is A
        ctx.check(was_current, f"it is not {A['name']}'s turn (current: {ctx.current['name']})")
        if facing:
            f = str(facing).upper()
            if f not in DIRS:
                raise GameError("facing must be N, E, S or W")
            A["facing"] = f
        if blade_pos is not None:
            bp = _pos(blade_pos, "blade_pos")
            if not _is_radius_mover(ctx, A):
                ctx.check(False, "blade_pos is only for Blades with a Bearer")
            else:
                ctx.check(_zone(ctx, A, bp) == _zone(ctx, A) and _free(cb, bp, A["cid"]),
                          f"blade_pos must be a free square in {A['name']}'s current radius")
                A["pos"] = bp
        _end_of_turn(ctx, A)
        cb["turns_taken"] += 1
        if A["cid"] in cb["order"]:
            cb["order"].remove(A["cid"])
            cb["order"].append(A["cid"])
        for sh in cb["pending_shifts"]:
            _shift(cb["order"], sh["cid"], sh["delta"])
        cb["pending_shifts"] = []
        nxt = _advance(ctx) if was_current else None
        end = _check_end(cb)
        out = {"ok": True,
               "summary": f"{A['name']} ends their turn" + (f"; {nxt['name']} is up." if nxt else ".")}
        if nxt:
            out.update(_context(ctx, nxt))
            if _status(nxt, "toppled"):
                out["must_skip"] = True
        return _finish(ctx, out)


def combat_swap_turn(engine, cid, partner=None, force=False):
    with engine.txn("combat_swap_turn") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        A = ctx.find(cid)
        ctx.check(ctx.current is A, "only the current actor can swap")
        team = ctx.team_of(A)
        ctx.check(team not in cb["swap_lock"], "turn swap is locked until every team member has taken a turn")
        mates = [c for c in cb["combatants"].values() if c is not A and not c["down"] and c["kind"] == "pc"
                 and ctx.team_of(c) == team and c["cid"] in cb["order"]]
        if partner:
            P = ctx.find(partner)
        elif mates:
            P = mates[0]
        else:
            raise GameError("no partner with a turn left to swap with")
        ctx.check(P in mates, f"{P['name']} is not a living teammate")
        ctx.check(A["turn"]["moved"] == 0 and not A["turn"]["acted"] and not A["turn"]["radius_moves"],
                  "swap before moving or acting")
        order = cb["order"]
        i, j = 0, order.index(P["cid"])
        order[i], order[j] = order[j], order[i]
        cb["swap_lock"][team] = [A["cid"], P["cid"]]
        A["turn"]["swapped"] = True
        _start_turn(ctx, P)
        ctx.ev(f"{A['name']} swaps turns with {P['name']}")
        out = {"ok": True, "summary": f"{A['name']} swaps with {P['name']}: {P['name']} acts now, {A['name']} takes {P['name']}'s later slot."}
        out.update(_context(ctx, P))
        return _finish(ctx, out)


def combat_delay(engine, cid, places, force=False):
    with engine.txn("combat_delay") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        A = ctx.find(cid)
        places = int(places)
        if places < 1:
            raise GameError("places must be >= 1")
        if A["cid"] not in cb["order"]:
            raise GameError(f"{A['name']} is not in the turn order")
        was_cur = ctx.current is A
        _shift(cb["order"], A["cid"], -places)
        out = {"ok": True, "summary": f"{A['name']} moves {places} place(s) later in the turn order."}
        if was_cur:
            A["start_applied"] = False
            nxt = _advance(ctx)
            out.update(_context(ctx, nxt)) if nxt else None
            out["summary"] += f" {nxt['name']} is up." if nxt else ""
        else:
            out.update(_context(ctx))
        return _finish(ctx, out)


def combat_life_force(engine, blade=None, give=None, decline=False, final_flicker=False, force=False):
    with engine.txn("combat_life_force") as st:
        ctx = Ctx(engine, st, force)
        cb = ctx.combat
        p = cb["pending"]
        if not p or p.get("type") != "life_force":
            raise GameError("no life_force pending")
        B = ctx.find(p["bearer"])
        out = {"ok": True}
        if decline:
            _next_pending_after(cb)
            _set_down(ctx, B, "no life force shared")
            out["summary"] = f"{B['name']} is not saved: {B['name']} and their natural Blades are down."
            _auto_advance(ctx, out)
            return _finish(ctx, out)
        names = [o["cid"] for o in p["blades"]]
        if blade is None and len(names) == 1:
            blade = names[0]
        if blade is None:
            raise GameError(f"which Blade shares? one of {names}")
        S = ctx.find(blade)
        ctx.check(S["cid"] in names, f"{S['name']} cannot share life force")
        aegis = ctx.has_talent(S, "protective_aegis")
        would = p["hp_after"]
        if final_flicker:
            ctx.check(ctx.has_talent(S, "final_flicker"), f"{S['name']} lacks Final Flicker")
            paid, new_hp = S["hp"], 1
        else:
            if give is None or int(give) < 1:
                raise GameError("give must be a positive HP value for the Bearer (or decline=true)")
            new_hp = min(int(give), B["max_hp"])
            paid = (new_hp - would) + (0 if aegis else 1)
            if paid > S["hp"]:
                raise GameError(f"{S['name']} has {S['hp']} HP but would pay {paid}; give at most "
                                f"{max(1, S['hp'] + would - (0 if aegis else 1))}")
        S["hp"] -= paid
        B["hp"] = new_hp
        cb["pending"] = None
        _next_pending(cb)
        if S["hp"] <= 0:
            _set_down(ctx, S, "spent all HP sharing life force")
        out["summary"] = (f"{S['name']} shares life force: {B['name']} restored to {new_hp} HP, "
                          f"{S['name']} pays {paid} (HP {S['hp']}/{S['max_hp']}).")
        out["digest"] = _digest(ctx)
        _auto_advance(ctx, out)
        return _finish(ctx, out)


def _next_pending_after(cb):
    cb["pending"] = None
    _next_pending(cb)


# ---------------------------------------------------------------- GM fiat
def _op_add(ctx, op):
    cb = ctx.combat
    e = {k: v for k, v in op.items() if k not in ("op", "index")}
    c = _build_combatant(ctx, e, cb)
    cb["combatants"][c["cid"]] = c
    if c["kind"] == "pc":
        cb["special"]["points"].setdefault(ctx.team_of(c), 0)
    if c["role"] == "blade":
        ref = e.get("bearer")
        b = ctx.find(ref) if ref else (cb["combatants"].get((ctx.st["teams"].get(c.get("team_id")) or {}).get("bearer")))
        if b:
            c["bearer_cid"] = b["cid"]
            b["blade_cids"].append(c["cid"])
    idx = op.get("index")
    cb["order"].insert(len(cb["order"]) if idx is None else int(idx), c["cid"])
    return f"added {c['name']} as {c['cid']}"


def _deep(d, patch):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            _deep(d[k], v)
        else:
            d[k] = v


def combat_adjust(engine, ops, reason=""):
    with engine.txn("combat_adjust") as st:
        ctx = Ctx(engine, st, True)
        cb = ctx.combat
        done = []
        for op in ops:
            o = op.get("op")
            if o in ("damage", "heal", "set_hp", "status_add", "status_remove", "move", "face", "shift_order",
                     "cooldown", "remove_combatant", "down", "revive", "card", "max_hp", "set_side"):
                c = ctx.find(op["cid"])
            if o == "damage":
                done.append(f"{c['name']} takes {_damage(ctx, c, op['n'], 'GM')} damage (hp {c['hp']})")
            elif o == "heal":
                done.append(f"{c['name']} healed {_heal(ctx, c, int(op['n']))} (hp {c['hp']})")
            elif o == "set_hp":
                n = int(op["n"])
                c["hp"] = min(n, c["max_hp"])
                if c["hp"] <= 0:
                    _set_down(ctx, c, "GM")
                done.append(f"{c['name']} hp set to {c['hp']}")
            elif o == "max_hp":
                c["max_hp"] = int(op["n"])
                c["hp"] = min(c["hp"], c["max_hp"])
                done.append(f"{c['name']} max hp {c['max_hp']}")
            elif o == "status_add":
                s = _add_status(ctx, c, op["id"], op.get("remaining", 1), op.get("unit"), op.get("source"),
                                op.get("data"), op.get("label"), op.get("kind"))
                done.append(f"{c['name']} +{op['id']}" if s else f"{op['id']} blocked on {c['name']}")
            elif o == "status_remove":
                done.append(f"{c['name']} -{op['id']}" if _remove_status(c, op["id"]) else f"{c['name']} had no {op['id']}")
            elif o == "move":
                p = _pos(op["to"], "to")
                if not _in_map(cb, p):
                    raise GameError(f"{p} outside map")
                if not _free(cb, p, c["cid"]):
                    occ = _occupant(cb, p)
                    raise GameError(f"move {c['name']} to {p}: square is " + (f"occupied by {occ['name']}" if occ else "blocked terrain")
                                    + " (move the occupant first, or change the cell with op 'cell')")
                old = list(c["pos"])
                c["pos"] = p
                _radius_changes(ctx, c, old, True)
                done.append(f"{c['name']} moved to {p}")
            elif o == "face":
                c["facing"] = str(op["dir"]).upper()
                done.append(f"{c['name']} faces {c['facing']}")
            elif o == "shift_order":
                _shift(cb["order"], c["cid"], int(op["delta"]))
                done.append(f"{c['name']} order shifted {op['delta']:+d}")
            elif o == "set_order":
                new = [ctx.find(x)["cid"] for x in op["order"]]
                if sorted(new) != sorted(cb["order"]):
                    raise GameError(f"set_order must list exactly the living combatants: {cb['order']}")
                cb["order"] = new
                done.append("order set")
            elif o == "special_points":
                t = op["team_id"]
                cur = cb["special"]["points"].get(t, 0)
                new = int(op["value"]) if "value" in op else cur + int(op["delta"])
                cb["special"]["points"][t] = max(0, min(18, new))
                done.append(f"team {t} special {cur}->{cb['special']['points'][t]}")
            elif o == "cooldown":
                while len(c["cooldowns"]) <= int(op["art"]):
                    c["cooldowns"].append(0)
                c["cooldowns"][int(op["art"])] = max(0, min(6, int(op["value"])))
                done.append(f"{c['name']} art {op['art']} cooldown {op['value']}")
            elif o == "add_combatant":
                done.append(_op_add(ctx, op))
            elif o == "remove_combatant":
                cb["order"] = [x for x in cb["order"] if x != c["cid"]]
                del cb["combatants"][c["cid"]]
                for x in cb["combatants"].values():
                    x["blade_cids"] = [b for b in x["blade_cids"] if b != c["cid"]]
                    if x.get("bearer_cid") == c["cid"]:
                        x["bearer_cid"] = None
                done.append(f"removed {c['name']}")
            elif o == "down":
                _set_down(ctx, c, "GM")
                done.append(f"{c['name']} down")
            elif o == "revive":
                c["down"], c["hp"] = False, max(1, int(op.get("hp", 1)))
                c["hp"] = min(c["hp"], c["max_hp"])
                if not _free(cb, c["pos"], c["cid"]):
                    spot = _nearest_free(cb, c["pos"], c["cid"])
                    if spot is None:
                        raise GameError(f"no free square near {c['pos']} to revive {c['name']} on")
                    c["pos"] = spot
                if c["cid"] not in cb["order"]:
                    cb["order"].append(c["cid"])
                done.append(f"{c['name']} revived at {c['hp']}")
            elif o == "cell":
                x, y = int(op["x"]), int(op["y"])
                if not _in_map(cb, [x, y]):
                    raise GameError(f"cell ({x},{y}) outside map")
                if op.get("type") is None:
                    cb["map"]["cells"].pop(f"{x},{y}", None)
                else:
                    t = op["type"]
                    if t not in CELL_DEFAULTS:
                        raise GameError(f"cell type {t!r} invalid")
                    bm, bs = CELL_DEFAULTS[t]
                    cb["map"]["cells"][f"{x},{y}"] = {"type": t, "label": op.get("label", ""),
                                                      "blocks_move": bool(op.get("blocks_move", bm)),
                                                      "blocks_sight": bool(op.get("blocks_sight", bs)),
                                                      "note": op.get("note", "")}
                done.append(f"cell ({x},{y}) -> {op.get('type')}")
            elif o == "chain_level":
                cb["special"]["chain_level"] = max(0, min(2, int(op["value"])))
                done.append(f"chain level {cb['special']['chain_level']}")
            elif o == "card":
                if not c.get("card"):
                    raise GameError(f"{c['name']} has no card")
                _deep(c["card"], op["patch"])
                done.append(f"{c['name']} card patched")
            elif o == "set_side":
                c["side"] = op["side"]
                done.append(f"{c['name']} side {c['side']}")
            else:
                raise GameError(f"unknown op {o!r}")
        ctx.ev(f"GM adjust ({reason or 'no reason'}): " + "; ".join(done))
        out = {"ok": True, "summary": "; ".join(done) + ".", "digest": _digest(ctx)}
        _auto_advance(ctx, out)
        return _finish(ctx, out)


def combat_end(engine, outcome, summary="", restore_hp=True):
    with engine.txn("combat_end") as st:
        ctx = Ctx(engine, st, True)
        cb = ctx.combat
        hp = {}
        for c in cb["combatants"].values():
            ch = ctx.char(c)
            if not ch:
                continue
            ch["hp"] = c["max_hp"] if restore_hp else max(0, c["hp"])
            hp[ch["id"]] = f"{ch['hp']}/{c['max_hp']}"
            for t in ch.get("talents", []):
                if t.get("per") == "combat":
                    t["used"] = False
        text = f"Combat '{cb['name']}' ended ({outcome}) after {cb['turns_taken']} turns."
        if summary:
            text += " " + summary
        engine.log(text, kind="event", tags=["combat"])
        st["clock"]["combats"] = st["clock"].get("combats", 0) + 1
        st["combat"] = None
        return {"ok": True, "summary": text, "hp": hp, "turns": cb["turns_taken"]}
