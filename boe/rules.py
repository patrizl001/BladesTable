"""Rules constants and pure rule helpers (no I/O except the talent catalog loader)."""
from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).parent / "data"

IDEAS = {
    "bravery": ["might", "willpower", "calculation"],
    "truth": ["gut", "experience", "knowledge"],
    "compassion": ["stamina", "empathy", "attunement"],
    "justice": ["swiftness", "improvisation", "passion"],
}
ATTRIBUTES = [a for lst in IDEAS.values() for a in lst]
ATTR_IDEA = {a: i for i, lst in IDEAS.items() for a in lst}
ELEMENT_IDEA = {
    "fire": "bravery", "water": "bravery", "wind": "truth", "ice": "truth",
    "earth": "compassion", "electricity": "compassion", "light": "justice", "dark": "justice",
}
ELEMENTS = list(ELEMENT_IDEA)
UNIQUE_EFFECTS = {
    "burning_blade": "fire", "arts_seal": "water", "blustering_gale": "wind", "freezing_force": "ice",
    "cradling_earth": "earth", "electrifying_burst": "electricity", "blade_of_light": "light",
    "shadow_manipulation": "dark",
}
SHARED_EFFECTS = {
    "invigorating_steam": "bravery", "bitter_snowstorm": "truth",
    "counter_spike": "compassion", "blinding_eclipse": "justice",
}

# tag id -> definition. cat_bp: BP category cost (None = special), create: creation cost,
# max: max instances of this tag on one art, roles: allowed roles.
TAGS: dict[str, dict[str, Any]] = {}


def _t(tid, cat, mx=1, create=1, roles=("bearer", "blade")):
    TAGS[tid] = {"id": tid, "category": cat, "max": mx, "create": create, "roles": roles}


_t("potency", "fundamentals", 5)
_t("healing_potion", "fundamentals", 1)
_t("cooldown", "fundamentals", 2)
_t("circle", "aoe", 2, 3)
_t("line", "aoe", 1, 3)
for _r in ("break", "topple", "launch", "stagger"):
    _t(_r, "reactions", 1)
_t("rush", "reactions", 2)
_t("side", "positionals", 1, 1, ("bearer",))
_t("rear", "positionals", 1, 1, ("bearer",))
_t("pincer", "positionals", 1, 1, ("blade",))
for _e in ("unique_effect", *SHARED_EFFECTS):
    _t(_e, "elemental", 1)
_t("range", "other", 5, 1)
_t("precise", "other", 1, 2)

CATEGORY_BP = {"fundamentals": 3, "aoe": 15, "reactions": 5, "positionals": 3, "elemental": 4}
CATEGORIES = ["fundamentals", "aoe", "reactions", "positionals", "elemental", "other"]
PRECISE_BP = 10
RANGE_BP_PER = 2

TAG_ALIASES = {
    "unique_elemental_effect": "unique_effect", "unique_elem_effect": "unique_effect",
    "unique_elemental": "unique_effect", "circle_attack": "circle", "line_attack": "line",
    "precise_attack": "precise", "side_advantage": "side", "rear_advantage": "rear",
    "pincer_attack": "pincer", "potion": "healing_potion", "heal": "healing_potion",
    "cooldown_reduction": "cooldown", "range_bonus": "range",
}

STARTING_POINTS = {
    "fresh_face": {"attr_points": 8, "field_skills": 2, "tags": 2, "per_cat": 1, "talent_ranks": 5},
    "part_time_hero": {"attr_points": 16, "field_skills": 3, "tags": 4, "per_cat": 2, "talent_ranks": 8},
    "veteran": {"attr_points": 24, "field_skills": 4, "tags": 6, "per_cat": 2, "talent_ranks": 11},
    "titan_savior": {"attr_points": 32, "field_skills": 5, "tags": 8, "per_cat": 3, "talent_ranks": 14},
}

ARC_ABILITIES = ("feeling_it", "reyn_time", "heronop")
MAX_ART_COUNT = 3
MAX_BASIC_RANGE_BONUS = 5


# ----------------------------------------------------------------- helpers
def slug(text: Any) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower().replace("'", "")).strip("_")
    return s


def pair_key(a: str, b: str) -> str:
    x, y = sorted([str(a), str(b)])
    return f"{x}|{y}"


def norm_starting_point(sp: Any) -> Optional[str]:
    s = slug(sp)
    s = {"fresh": "fresh_face", "parttime_hero": "part_time_hero", "parttime": "part_time_hero",
         "part_time": "part_time_hero", "titan": "titan_savior", "titansavior": "titan_savior",
         "freshface": "fresh_face", "parttimehero": "part_time_hero"}.get(s, s)
    return s if s in STARTING_POINTS else None


def norm_attr(a: Any) -> Optional[str]:
    s = slug(a)
    return s if s in ATTR_IDEA else None


def norm_element(e: Any) -> Optional[str]:
    s = slug(e)
    return s if s in ELEMENT_IDEA else None


def norm_tag(t: Any) -> Optional[str]:
    s = slug(t)
    s = re.sub(r"_?[+-]?_?\d+$", "", s) if s not in TAGS else s
    s = TAG_ALIASES.get(s, s)
    return s if s in TAGS else None


def norm_tags(raw: Any) -> tuple[dict[str, int], list[str]]:
    """dict {tag: n} or list of tag names (repeats = count) -> ({tag: n}, errors)."""
    errs: list[str] = []
    out: dict[str, int] = {}
    if raw is None:
        return out, errs
    items: list[tuple[Any, int]] = []
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                items.append((k, int(v)))
            except (TypeError, ValueError):
                errs.append(f"tag {k!r}: count must be an integer, got {v!r}")
    elif isinstance(raw, (list, tuple)):
        items = [(k, 1) for k in raw]
    else:
        errs.append("tags must be a dict {tag: count} or a list of tag names")
        return out, errs
    for k, n in items:
        tid = norm_tag(k)
        if tid is None:
            errs.append(f"unknown art tag {k!r}; valid: {', '.join(TAGS)}")
        elif n > 0:
            out[tid] = out.get(tid, 0) + n
    return out, errs


def attr_rank_cost(rank: int) -> int:
    """Creation cost of buying rank `rank` (2..12)."""
    return 1 if rank <= 4 else 2 if rank <= 8 else 3


def attr_creation_cost(value: int) -> int:
    return sum(attr_rank_cost(r) for r in range(2, value + 1))


def category_counts(tags: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t, n in tags.items():
        c = TAGS[t]["category"]
        out[c] = out.get(c, 0) + n
    return out


def elemental_tag_ok(tag: str, affinities: list[str]) -> bool:
    if tag == "unique_effect":
        return bool(affinities)
    idea = SHARED_EFFECTS.get(tag)
    return any(ELEMENT_IDEA.get(a) == idea for a in affinities)


def art_tag_bp_cost(tags: dict[str, int], tag: str) -> int:
    """BP cost of adding one instance of `tag` to an art with `tags`."""
    if tag == "precise":
        return PRECISE_BP
    if tag == "range":
        return RANGE_BP_PER * (tags.get("range", 0) + 1)
    cat = TAGS[tag]["category"]
    return CATEGORY_BP[cat] * (category_counts(tags).get(cat, 0) + 1)


def art_tag_refund(tags: dict[str, int], tag: str) -> int:
    """BP regained by refunding one instance of `tag` (cost of the most recent tag in that category)."""
    if tag == "precise":
        return PRECISE_BP
    if tag == "range":
        return RANGE_BP_PER * tags.get("range", 0)
    cat = TAGS[tag]["category"]
    return CATEGORY_BP[cat] * category_counts(tags).get(cat, 0)


# --------------------------------------------------------------- talents
def _warn(msg: str) -> None:
    print(f"[boe] warning: {msg}", file=sys.stderr)


@lru_cache(maxsize=1)
def _talents_cached(path: str, mtime: float) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("talents", []))


def talent_catalog() -> Optional[list[dict]]:
    """Talent catalog, or None when talents.json is missing/unreadable."""
    p = DATA_DIR / "talents.json"
    try:
        return _talents_cached(str(p), p.stat().st_mtime)
    except (OSError, ValueError):
        return None


def find_talent(ref: Any) -> Optional[dict]:
    cat = talent_catalog()
    if cat is None:
        return None
    s = slug(ref)
    for t in cat:
        if slug(t.get("id", "")) == s or slug(t.get("name", "")) == s:
            return t
    return None


def search_talents(ref: Any, limit: int = 5) -> list[str]:
    cat = talent_catalog() or []
    s = slug(ref)
    return [t["name"] for t in cat if s and (s in slug(t.get("name", "")) or slug(t.get("name", "")) in s)][:limit]


def talent_rank_range(t: dict) -> tuple[int, int]:
    if t.get("rank") is not None:
        return int(t["rank"]), int(t["rank"])
    lo = int(t.get("rank_min") or 1)
    hi = int(t.get("rank_max") or lo)
    return lo, hi


def talent_is_upgradable(t: dict) -> bool:
    lo, hi = talent_rank_range(t)
    return hi > lo


def char_talent_ids(char: dict) -> set[str]:
    return {slug(t.get("id") or t.get("name")) for t in char.get("talents", [])}


def char_talent(char: dict, ref: Any) -> Optional[dict]:
    s = slug(ref)
    for t in char.get("talents", []):
        if slug(t.get("id")) == s or slug(t.get("name")) == s:
            return t
    return None


# --------------------------------------------------------------- derived
def recompute_derived(c: dict) -> dict:
    """Fill c['derived'] from attributes, talents, role. Returns the derived dict."""
    a = c.get("attributes", {})
    g = lambda k: int(a.get(k, 1))  # noqa: E731
    tids = char_talent_ids(c)
    amalgam = char_talent(c, "living_amalgam")
    choice = slug(amalgam.get("choice", "")) if amalgam else ""
    max_hp = g("willpower") + g("stamina") + 4
    for tid, bonus in (("indomitable", 2), ("fortified", 4), ("steel_flesh", 6)):
        if tid in tids:
            max_hp += bonus
    if amalgam and "hp" in choice:
        max_hp += 4
    init = max(g("improvisation") + g("gut"), g("calculation") + g("experience"))
    if "first_strike" in tids:
        init += 3
    if amalgam and ("init" in choice):
        init += 3
    role = c.get("role", "bearer")
    if role == "blade":
        movement = 1 + ("swift_slide" in tids) + (1 if amalgam and "radius" in choice else 0)
    else:
        movement = 5 if "fleet_of_foot" in tids else 4 if "quick_step" in tids else 3
    cd = [0, 2, 4]
    if "prime_position" in tids:
        cd = [0, 0, 2]
    elif "secondary_accelerator" in tids:
        cd = [0, 0, 4]
    ideas = {i: sum(g(x) for x in lst) for i, lst in IDEAS.items()}
    d = {
        "max_hp": max_hp, "initiative_pool": init, "movement": movement,
        "basic_range": 1 + int(c.get("basic_range_bonus", 0)),
        "max_radius": 5 if "radius_master" in tids else 3,
        "start_cooldowns": cd, "ideas": ideas,
    }
    c["derived"] = d
    return d


def is_untouched(c: dict) -> bool:
    return "untouched" in char_talent_ids(c)
