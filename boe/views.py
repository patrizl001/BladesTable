"""Player-view redaction: what the web UI may see. Nothing gm_only, no check/net for check rolls,
no NPC cards or exact NPC HP."""
from __future__ import annotations

import copy
import re
from typing import Any

PUBLIC_ROLL_KINDS = {"attack", "defense", "special"}
_HP_RE = re.compile(r"\s*[\(\[]?\b(?:hp|HP)\b(?:\s+(?:set\s+to|is|to))?[:=\s]*-?\d+(?:\s*/\s*\d+)?[\)\]]?")
_HP_ARROW_RE = re.compile(r"\s*[\(\[]?-?\d+\s*/\s*\d+\s*(?:hp|HP)[\)\]]?")


def condition(hp: Any, max_hp: Any, down: bool = False) -> str:
    try:
        hp, mx = float(hp), float(max_hp)
    except (TypeError, ValueError):
        return "fresh"
    if down or hp <= 0:
        return "down"
    r = hp / mx if mx > 0 else 1
    if r >= 1:
        return "fresh"
    if r > 0.6:
        return "scratched"
    if r > 0.3:
        return "hurt"
    return "badly hurt"


def _redact_combat(cb: dict) -> dict:
    cb = copy.deepcopy(cb)
    npc_names = []
    for c in cb.get("combatants", {}).values():
        if c.get("kind") == "npc" or c.get("card") is not None:
            npc_names.append(c.get("name", ""))
            c["condition"] = condition(c.get("hp"), c.get("max_hp"), c.get("down", False))
            c["hp"] = None
            c["max_hp"] = None
            c.pop("card", None)
    log = []
    for entry in cb.get("log", []) or []:
        if isinstance(entry, dict):
            e = dict(entry)
            t = str(e.get("text", ""))
            if t.startswith("GM adjust"):
                # fiat edits may mention NPC hp, card patches and the GM's private reason
                t = "The Architect adjusts the situation."
            if any(n and n in t for n in npc_names) or _HP_RE.search(t):
                t = _HP_ARROW_RE.sub("", _HP_RE.sub("", t))
            e["text"] = t
            log.append(e)
    if "log" in cb:
        cb["log"] = log
    # pending special_split / life_force carry only totals, which are public once rolled
    return cb


def _redact_roll(r: dict) -> dict:
    r = dict(r)
    if r.get("kind") not in PUBLIC_ROLL_KINDS:
        r.pop("check", None)
        r.pop("net", None)
    return r


def _redact_entity(e: dict) -> dict:
    e = dict(e)
    e.pop("gm_notes", None)
    e.pop("card", None)
    return e


def player_view(state: dict | None, version: int = 0, campaigns: list | None = None) -> dict:
    if not state:
        return {"ok": True, "version": version, "has_campaign": False, "campaigns": campaigns or []}
    s = state
    return copy.deepcopy({
        "ok": True, "version": s["version"], "has_campaign": True,
        "meta": s["meta"], "clock": s["clock"], "scene": s["scene"],
        "characters": s["characters"], "teams": s["teams"], "affinity": s["affinity"],
        "entities": {k: _redact_entity(e) for k, e in s["entities"].items()
                     if not e.get("gm_only") and e.get("kind") != "secret"},
        "journal": [j for j in s["journal"] if not j.get("gm_only")][-150:],
        "rolls": [_redact_roll(r) for r in s["rolls"][-60:]],
        "combat": _redact_combat(s["combat"]) if s.get("combat") else None,
        "sessions": s["sessions"], "arcs": s["arcs"],
    })
