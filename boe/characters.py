"""Characters: creation/validation, BP advancement, bonds, affinity, checks, abilities.

Every public function is `fn(engine, ...) -> dict` and raises GameError for usage errors
(tools turn that into {"ok": false, "errors": [...]}). Rule violations that the GM may override
return {"ok": false, "errors": [...]} unless force=True.
"""
from __future__ import annotations

import copy
from typing import Any, Optional

from . import dice, reference, rules
from .engine import Engine, GameError
from .rules import ATTRIBUTES, CATEGORIES, TAGS, slug


# ------------------------------------------------------------------ utils
class Issues:
    """errors = structural (never forceable); violations = rule breaks (force=True overrides)."""

    def __init__(self):
        self.errors: list[str] = []
        self.violations: list[str] = []
        self.warnings: list[str] = []

    def fatal(self, m: str):
        self.errors.append(m)

    def rule(self, m: str):
        self.violations.append(m)

    def warn(self, m: str):
        self.warnings.append(m)


def find_char(state: dict, ref: Any, required: bool = True) -> Optional[dict]:
    chars = state["characters"]
    if ref is None or ref == "":
        if required:
            raise GameError("character id/name required")
        return None
    if ref in chars:
        return chars[ref]
    s = slug(ref)
    for c in chars.values():
        if slug(c["id"]) == s or slug(c["name"]) == s:
            return c
    if required:
        raise GameError(f"no character {ref!r}; characters: {[c['id'] for c in chars.values()] or 'none yet'}")
    return None


def pcs(state: dict) -> list[dict]:
    return list(state["characters"].values())


def refresh(c: dict) -> None:
    old = (c.get("derived") or {}).get("max_hp")
    rules.recompute_derived(c)
    mx = c["derived"]["max_hp"]
    if old is not None and mx > old:
        c["hp"] = int(c.get("hp", old)) + (mx - old)
    c["hp"] = max(0, min(int(c.get("hp", mx)), mx))


def talent_label(t: dict) -> str:
    lbl = t["name"]
    lo_hi = None
    r = t.get("rank")
    if r is not None:
        lbl += f" r{r}"
    if t.get("choice"):
        lbl += f" ({t['choice']})"
    return lbl


def digest(c: dict, brief: bool = False) -> dict:
    d = c.get("derived", {})
    out: dict[str, Any] = {
        "id": c["id"], "name": c["name"], "role": c["role"], "controller": c.get("controller"),
        "hp": f"{c.get('hp')}/{d.get('max_hp')}", "bp": c["bp"],
        "attributes": c["attributes"], "affinities": c["affinities"],
    }
    if brief:
        return {k: out[k] for k in ("id", "name", "role", "hp", "bp")}
    out.update({
        "pronouns": c.get("pronouns", ""), "team_id": c.get("team_id"), "partner_ids": c.get("partner_ids", []),
        "field_skills": [f["name"] for f in c.get("field_skills", [])],
        "basic_range_bonus": c.get("basic_range_bonus", 0),
        "arts": [{"i": i, "name": a["name"], "tags": a["tags"]} for i, a in enumerate(c.get("arts", []))],
        "talents": [talent_label(t) for t in c.get("talents", [])],
        "arc_abilities_available": [k for k, v in c.get("arc_abilities", {}).items() if v],
        "derived": d,
        "bonds": {k: v["name"] for k, v in c.get("bonds", {}).items()},
        "inventory": c.get("inventory", []), "dead": c.get("dead", False),
        "tag_refund_available": c.get("tag_refund_available", False),
    })
    return out


def _fail(issues: Issues, force: bool) -> Optional[dict]:
    errs = issues.errors + ([] if force else issues.violations)
    if errs:
        r = {"ok": False, "errors": errs}
        if issues.warnings:
            r["warnings"] = issues.warnings
        if issues.violations and not force and not issues.errors:
            r["hint"] = "re-send with force=true to apply anyway (GM override of the rule)"
        return r
    return None


def _forced_warnings(issues: Issues, force: bool) -> list[str]:
    w = list(issues.warnings)
    if force:
        w += [f"FORCED: {v}" for v in issues.violations]
    return w


def wire_teams(state: dict, issues: Optional[Issues] = None) -> None:
    """Make partner_ids symmetric and rebuild teams/team_id from them."""
    chars = state["characters"]
    for c in chars.values():
        for pid in list(c.get("partner_ids", [])):
            o = chars.get(pid)
            if o and c["id"] not in o.setdefault("partner_ids", []):
                o["partner_ids"].append(c["id"])
    teams: dict[str, dict] = {}
    for c in chars.values():
        c["team_id"] = None
    for b in [c for c in chars.values() if c["role"] == "bearer"]:
        tid = f"t_{b['id']}"
        blades = [chars[p] for p in b.get("partner_ids", []) if p in chars and chars[p]["role"] == "blade"]
        teams[tid] = {"id": tid, "bearer": b["id"], "blades": [x["id"] for x in blades]}
        b["team_id"] = tid
        for x in blades:
            if x["team_id"] is None:
                x["team_id"] = tid
            elif issues:
                issues.warn(f"blade {x['name']} is partnered with more than one Bearer; kept {x['team_id']}")
    state["teams"] = teams


# ------------------------------------------------------- creation options
def creation_options(engine: Engine, role: str = "") -> dict:
    st = engine.require_state()
    sp_key = st["meta"]["starting_point"]
    sp = rules.STARTING_POINTS[sp_key]
    cat = rules.talent_catalog()
    role = role.lower().strip()
    out: dict[str, Any] = {
        "ok": True, "starting_point": sp_key, "budgets": {
            "attribute_points": sp["attr_points"],
            "attribute_costs": "all attributes start at 1, max 12; rank 2-4 cost 1 each, 5-8 cost 2, 9-12 cost 3",
            "field_skills": f"{sp['field_skills']} of your own (plus free 'Elemental Mastery', added automatically)",
            "elemental_affinities": "exactly 1 at creation (Untouched archetype: none, and attunement is 0)",
            "arts": f"exactly {rules.MAX_ART_COUNT}; each gets a free potency:1. Per art: {sp['tags']} creation tags, "
                    f"max {sp['per_cat']} tag instances per category (free potency not counted)",
            "talent_ranks": f"total rank {sp['talent_ranks']}",
        },
        "art_tags": {t: {"category": d["category"], "max": d["max"], "creation_cost": d["create"],
                         **({"roles": list(d["roles"])} if len(d["roles"]) < 2 else {})}
                     for t, d in TAGS.items()},
        "art_tag_rules": [
            "tags dict is the art's FINAL tag set, e.g. {\"potency\":2,\"cooldown\":1}; the free potency:1 is "
            "included automatically (potency:2 = free + one paid).",
            "only one distinct tag per category except fundamentals (rush x2 or circle x2 are fine; break+topple is not)",
            "elemental tags need a matching affinity: unique_effect = any; invigorating_steam fire/water; "
            "bitter_snowstorm wind/ice; counter_spike earth/electricity; blinding_eclipse light/dark",
            "side/rear = bearer only, pincer = blade only; aoe costs 3 creation tags, precise costs 2",
        ],
        "elements": rules.ELEMENT_IDEA,
        "attributes": rules.IDEAS,
        "sheet_example": {
            "name": "Pyre", "role": "bearer", "pronouns": "she/her", "weapon": "whip-sword",
            "partner": "Doma", "controller": "player",
            "attributes": {"might": 3, "willpower": 4, "gut": 3},
            "affinities": ["fire"], "field_skills": [{"name": "Salvaging", "description": "..."}],
            "arts": [{"name": "Lash", "tags": {"potency": 2, "cooldown": 1}}, {"name": "Anchor"}, {"name": "Flare"}],
            "talents": ["Indomitable", {"name": "Fame", "rank": 2}],
            "bonds": {"Doma": {"name": "Best Friend", "benefit": "...", "drawback": "..."}},
        },
    }
    if cat is None:
        out["talents"] = "talent catalog not built yet; sheets may list {name, rank} verbatim (a warning is issued)"
    else:
        rows = []
        for t in cat:
            if role in ("bearer", "blade") and t.get("role") not in (role, "any", "pair", None):
                continue
            lo, hi = rules.talent_rank_range(t)
            rows.append(f"{t['name']} ({lo if lo == hi else f'{lo}-{hi}'})"
                        + ("*" if t.get("creation_only") else ""))
        out["talents"] = {"legend": "name (rank); * = creation-only. Use talent_lookup for text/prereqs.",
                          "list": rows}
    return out


# ----------------------------------------------------------- sheet parsing
def _parse_art_tags(raw, art_name, iss: Issues):
    tags, errs = rules.norm_tags(raw)
    for e in errs:
        iss.fatal(f"art {art_name!r}: {e}")
    return tags


def _resolve_talent(raw: Any, iss: Issues, force_catalog_missing_warned: list) -> Optional[dict]:
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        iss.fatal(f"talent entry must be a name or {{name|id, rank, choice}}, got {raw!r}")
        return None
    ref = raw.get("id") or raw.get("name")
    if not ref:
        iss.fatal(f"talent entry needs 'name' or 'id': {raw!r}")
        return None
    cat = rules.talent_catalog()
    t = rules.find_talent(ref)
    if cat is not None and t is None:
        near = rules.search_talents(ref)
        iss.fatal(f"unknown talent {ref!r}" + (f"; did you mean {near}?" if near else
                  "; use talent_lookup to find the exact name"))
        return None
    rank = raw.get("rank")
    if t is None:  # catalog missing
        if not force_catalog_missing_warned:
            iss.warn("talent catalog (talents.json) missing: talents accepted verbatim, prerequisites unchecked")
            force_catalog_missing_warned.append(1)
        try:
            rank_i = int(rank if rank is not None else 1)
        except (TypeError, ValueError):
            iss.fatal(f"talent {ref!r}: rank must be an integer")
            return None
        return {"id": slug(ref), "name": str(raw.get("name") or ref), "rank": rank_i,
                "choice": str(raw.get("choice", "")), "per": raw.get("per"), "used": False, "_cat": None}
    lo, hi = rules.talent_rank_range(t)
    try:
        rank_i = int(rank) if rank is not None else lo
    except (TypeError, ValueError):
        iss.fatal(f"talent {t['name']}: rank must be an integer")
        return None
    if not lo <= rank_i <= hi:
        iss.rule(f"talent {t['name']} exists at rank {lo}" + (f"-{hi}" if hi != lo else "") + f", not {rank_i}")
    return {"id": t["id"], "name": t["name"], "rank": rank_i, "choice": str(raw.get("choice", "")),
            "per": t.get("per"), "used": False, "_cat": t}


def check_talent_prereqs(t: dict, role: str, attrs: dict, owned_ids: set, iss: Issues,
                         creation: bool, owned_cat: Optional[list] = None) -> None:
    """t is the catalog entry. owned_ids: ids of the character's other talents."""
    name = t["name"]
    if t.get("role") in ("bearer", "blade") and t["role"] != role:
        iss.rule(f"talent {name} is {t['role']}-only; this character is a {role}")
    if t.get("creation_only") and not creation:
        iss.rule(f"talent {name} can only be taken at character creation")
    req = t.get("requires") or {}
    for a, v in (req.get("attributes") or {}).items():
        if int(attrs.get(a, 1)) < int(v):
            iss.rule(f"talent {name} requires {a} {v} (has {attrs.get(a, 1)})")
    for need in req.get("talents") or []:
        if slug(need) not in owned_ids:
            iss.rule(f"talent {name} requires talent {need}")
    if req.get("archetype") and slug(req["archetype"]) not in owned_ids:
        iss.rule(f"talent {name} requires the {req['archetype']} archetype talent")
    for ex in t.get("excludes") or []:
        if slug(ex) in owned_ids:
            iss.rule(f"talent {name} cannot be combined with {ex}")


def _resolve_refs(state: dict, refs: Any) -> list[str]:
    if refs is None:
        return []
    if isinstance(refs, str):
        refs = [refs]
    out = []
    for r in refs:
        c = find_char(state, r, required=False)
        out.append(c["id"] if c else slug(r))
    return out


def validate_and_build(state: dict, sheet: dict) -> tuple[Optional[dict], Issues, dict]:
    iss = Issues()
    spend: dict[str, Any] = {}
    if not isinstance(sheet, dict):
        iss.fatal("sheet must be an object")
        return None, iss, spend
    sp_key = state["meta"]["starting_point"]
    sp = rules.STARTING_POINTS[sp_key]
    name = str(sheet.get("name", "")).strip()
    if not name:
        iss.fatal("sheet.name is required")
    role = str(sheet.get("role", "")).strip().lower()
    if role not in ("bearer", "blade"):
        iss.fatal("sheet.role must be 'bearer' or 'blade'")
    cid = slug(sheet.get("id") or name).replace("_", "-") or "pc"
    if cid in state["characters"] or find_char(state, name, required=False):
        iss.fatal(f"a character named/identified {name!r} already exists")

    # talents first (untouched changes attributes/affinity rules)
    warned: list = []
    talents = [t for t in (_resolve_talent(r, iss, warned) for r in (sheet.get("talents") or [])) if t]
    tids = {slug(t["id"]) for t in talents}
    untouched = "untouched" in tids
    if untouched and role == "blade":
        iss.rule("Untouched is a Bearer archetype")

    # attributes
    attrs = {a: 1 for a in ATTRIBUTES}
    raw_attrs = sheet.get("attributes") or {}
    if not isinstance(raw_attrs, dict):
        iss.fatal("attributes must be an object {attribute: value}")
        raw_attrs = {}
    for k, v in raw_attrs.items():
        a = rules.norm_attr(k)
        if a is None:
            iss.fatal(f"unknown attribute {k!r}; valid: {', '.join(ATTRIBUTES)}")
            continue
        try:
            iv = int(v)
        except (TypeError, ValueError):
            iss.fatal(f"attribute {k}: value must be an integer")
            continue
        if not 1 <= iv <= 12:
            iss.rule(f"attribute {a} must be 1-12 (got {iv})")
            iv = max(1, min(12, iv))
        attrs[a] = iv
    if untouched:
        if attrs["attunement"] > 1:
            iss.warn("Untouched archetype: attunement forced to 0 (not charged)")
        attrs["attunement"] = 0
    spent = sum(rules.attr_creation_cost(v) for a, v in attrs.items() if not (untouched and a == "attunement"))
    spend["attributes"] = f"{spent}/{sp['attr_points']}"
    if spent > sp["attr_points"]:
        iss.rule(f"attributes cost {spent} points but {sp_key} has {sp['attr_points']} "
                 f"(ranks 2-4 cost 1, 5-8 cost 2, 9-12 cost 3)")
    elif spent < sp["attr_points"]:
        iss.warn(f"{sp['attr_points'] - spent} attribute point(s) unspent")

    # affinities
    raw_aff = sheet.get("affinities", sheet.get("affinity", []))
    if isinstance(raw_aff, str):
        raw_aff = [raw_aff]
    affs: list[str] = []
    for e in raw_aff or []:
        el = rules.norm_element(e)
        if el is None:
            iss.fatal(f"unknown element {e!r}; valid: {', '.join(rules.ELEMENTS)}")
        elif el not in affs:
            affs.append(el)
    if untouched:
        if affs:
            iss.rule("Untouched characters have no elemental affinity")
    elif len(affs) != 1:
        iss.rule(f"exactly one elemental affinity at creation (got {len(affs)}); more are bought with BP")

    # field skills
    fs: list[dict] = []
    for f in sheet.get("field_skills") or []:
        if isinstance(f, str):
            f = {"name": f}
        if not isinstance(f, dict) or not f.get("name"):
            iss.fatal(f"field skill needs a name: {f!r}")
            continue
        if slug(f["name"]) == "elemental_mastery":
            continue
        fs.append({"name": str(f["name"]), "description": str(f.get("description", ""))})
    spend["field_skills"] = f"{len(fs)}/{sp['field_skills']}"
    if len(fs) > sp["field_skills"]:
        iss.rule(f"{len(fs)} field skills but {sp_key} allows {sp['field_skills']} (Elemental Mastery is free and automatic)")
    elif len(fs) < sp["field_skills"]:
        iss.warn(f"{sp['field_skills'] - len(fs)} field skill slot(s) unused")
    fs.insert(0, {"name": "Elemental Mastery",
                  "description": "Manipulate ether aligned with your elemental affinities with great control."})

    # arts
    raw_arts = sheet.get("arts") or []
    if not isinstance(raw_arts, list):
        iss.fatal("arts must be a list of 3 arts")
        raw_arts = []
    if len(raw_arts) != rules.MAX_ART_COUNT:
        iss.rule(f"exactly {rules.MAX_ART_COUNT} arts required (got {len(raw_arts)})")
    arts = []
    for i, ra in enumerate(raw_arts[:rules.MAX_ART_COUNT]):
        if isinstance(ra, str):
            ra = {"name": ra}
        if not isinstance(ra, dict):
            iss.fatal(f"art {i}: must be an object {{name, description, tags}}")
            continue
        aname = str(ra.get("name") or f"Art {i + 1}")
        tags = _parse_art_tags(ra.get("tags"), aname, iss)
        tags.setdefault("potency", 1)
        _validate_art_creation(aname, tags, role, affs, sp, iss)
        arts.append({"name": aname, "description": str(ra.get("description", "")), "tags": tags})
    while len(arts) < rules.MAX_ART_COUNT and not iss.errors:
        arts.append({"name": f"Art {len(arts) + 1}", "description": "", "tags": {"potency": 1}})

    # talents: cost / prereqs
    total_rank = sum(int(t["rank"]) for t in talents)
    spend["talent_ranks"] = f"{total_rank}/{sp['talent_ranks']}"
    if total_rank > sp["talent_ranks"]:
        iss.rule(f"talents total rank {total_rank} but {sp_key} allows {sp['talent_ranks']}")
    elif total_rank < sp["talent_ranks"]:
        iss.warn(f"{sp['talent_ranks'] - total_rank} talent rank(s) unspent")
    seen = set()
    archetypes = 0
    for t in talents:
        if t["id"] in seen:
            iss.fatal(f"talent {t['name']} listed twice")
        seen.add(t["id"])
        cat = t.pop("_cat")
        if cat is None:
            continue
        if cat.get("category") == "archetype":
            archetypes += 1
        if cat.get("category") == "pair":
            iss.warn(f"pair talent {t['name']}: the partner must take it too")
        check_talent_prereqs(cat, role, attrs, tids - {slug(t["id"])}, iss, creation=True)
    if archetypes > 1:
        iss.rule("only one archetype talent is allowed")

    # partners / bonds
    partners = _resolve_refs(state, sheet.get("partner_ids", sheet.get("partners", sheet.get("partner"))))
    for p in partners:
        if p not in state["characters"]:
            iss.warn(f"partner {p!r} does not exist yet; they will be linked when created with that name")
        elif state["characters"][p]["role"] == role:
            iss.rule(f"partners must be one Bearer and one Blade ({p} is also a {role})")
    bonds: dict[str, dict] = {}
    rb = sheet.get("bonds") or {}
    if isinstance(rb, dict):
        for who, b in rb.items():
            o = find_char(state, who, required=False)
            if not o:
                iss.warn(f"bond with unknown character {who!r} skipped (use bond_set once they exist)")
                continue
            bonds[o["id"]] = _norm_bond(b)
    bp = sheet.get("bp")
    bp_v = int(bp) if isinstance(bp, (int, float)) else 0

    if iss.errors:
        return None, iss, spend
    ctrl = str(sheet.get("controller", "player")).lower()
    if ctrl not in ("player", "architect"):
        iss.warn("controller must be 'player' or 'architect'; using 'player'")
        ctrl = "player"
    c = {
        "id": cid, "name": name, "pronouns": str(sheet.get("pronouns", "")), "role": role,
        "controller": ctrl, "team_id": None, "partner_ids": partners,
        "weapon": str(sheet.get("weapon", "")), "home_titan": str(sheet.get("home_titan", "")),
        "appearance": str(sheet.get("appearance", "")), "personality": str(sheet.get("personality", "")),
        "background": str(sheet.get("background", "")),
        "attributes": attrs, "affinities": affs, "field_skills": fs, "basic_range_bonus": 0,
        "arts": arts, "talents": talents,
        "bp": {"current": bp_v, "total": bp_v},
        "arc_abilities": {k: True for k in rules.ARC_ABILITIES},
        "bonds": bonds, "inventory": list(sheet.get("inventory") or []), "notes": str(sheet.get("notes", "")),
        "dead": False, "tag_refund_available": False, "hp": 1, "derived": {},
    }
    refresh(c)
    c["hp"] = c["derived"]["max_hp"]
    return c, iss, spend


def _norm_bond(b: Any) -> dict:
    if isinstance(b, str):
        b = {"name": b}
    b = b if isinstance(b, dict) else {}
    return {"name": str(b.get("name", "")), "benefit": str(b.get("benefit", "")),
            "drawback": str(b.get("drawback", ""))}


def _validate_art_creation(aname: str, tags: dict, role: str, affs: list, sp: dict, iss: Issues) -> None:
    free = dict(tags)
    free["potency"] = max(0, free.get("potency", 1) - 1)  # the first potency is free
    cost = 0
    cats: dict[str, int] = {}
    distinct: dict[str, set] = {}
    for t, n in free.items():
        if n <= 0:
            continue
        d = TAGS[t]
        total_n = tags[t]
        if total_n > d["max"]:
            iss.rule(f"art {aname!r}: {t} max {d['max']} (got {total_n})")
        if role in ("bearer", "blade") and role not in d["roles"]:
            iss.rule(f"art {aname!r}: {t} is {'/'.join(d['roles'])}-only; this character is a {role}")
        if d["category"] == "elemental" and not rules.elemental_tag_ok(t, affs):
            need = "any elemental affinity" if t == "unique_effect" else \
                f"an affinity aligned with {rules.SHARED_EFFECTS[t]}"
            iss.rule(f"art {aname!r}: {t} requires {need}")
        cost += d["create"] * n
        cats[d["category"]] = cats.get(d["category"], 0) + n
        distinct.setdefault(d["category"], set()).add(t)
    for c, n in cats.items():
        if c != "other" and n > sp["per_cat"]:
            iss.rule(f"art {aname!r}: {n} tags in category {c}, max {sp['per_cat']} per category for this starting point")
        if c not in ("fundamentals", "other") and len(distinct[c]) > 1:
            iss.rule(f"art {aname!r}: only one distinct tag per category ({c}: {sorted(distinct[c])})")
    if cost > sp["tags"]:
        iss.rule(f"art {aname!r}: tags cost {cost} but only {sp['tags']} allowed "
                 f"(aoe tags count 3, precise 2; free potency:1 excluded)")
    elif cost < sp["tags"]:
        iss.warn(f"art {aname!r}: {sp['tags'] - cost} creation tag(s) unspent")


# ---------------------------------------------------------------- create
def character_create(engine: Engine, sheet: dict, force: bool = False) -> dict:
    st = engine.require_state()
    c, iss, spend = validate_and_build(st, sheet)
    bad = _fail(iss, force) if c is not None else {"ok": False, "errors": iss.errors + iss.violations,
                                                    "hint": "fix the structural errors first (force=true cannot override them)",
                                                    **({"warnings": iss.warnings} if iss.warnings else {})}
    if bad:
        return bad
    warnings = _forced_warnings(iss, force)
    with engine.txn(f"character_create {c['name']}"):
        s = engine.state
        s["characters"][c["id"]] = c
        for o in s["characters"].values():
            if o["id"] != c["id"]:
                s["affinity"].setdefault(rules.pair_key(c["id"], o["id"]), 0)
        # reciprocal links from earlier-created characters naming this one
        for o in s["characters"].values():
            if c["id"] in o.get("partner_ids", []) and o["id"] not in c["partner_ids"]:
                c["partner_ids"].append(o["id"])
        wire_teams(s, iss)
        for t in s["teams"].values():
            if len(t["blades"]) > 2:
                warnings.append(f"Bearer {t['bearer']} has {len(t['blades'])} Blades (rules allow at most 2)")
        warnings += [w for w in iss.warnings if w not in warnings]
        if force and iss.violations:
            engine.log(f"{c['name']} created with rule overrides: " + "; ".join(iss.violations), "system")
        engine.log(f"{c['name']} ({c['role']}) joins the party.", "system")
    r = {"ok": True, "character": digest(c), "spent": spend}
    if warnings:
        r["warnings"] = list(dict.fromkeys(warnings))
    r["next"] = "Create the partner/rest of the party, set bonds with bond_set, then session_begin."
    return r


# ---------------------------------------------------------------- update
_NARRATIVE = {"name", "pronouns", "weapon", "home_titan", "appearance", "personality", "background",
              "controller", "notes", "inventory", "hp", "dead", "role"}
_MERGE = {"attributes", "bp", "arc_abilities", "bonds"}
_REPLACE = {"affinities", "field_skills", "arts", "talents", "basic_range_bonus", "partner_ids",
            "tag_refund_available"}
_HELPERS = {"inventory_add", "inventory_remove", "hp_delta"}


def character_update(engine: Engine, char_id: str, patch: dict) -> dict:
    if not isinstance(patch, dict) or not patch:
        raise GameError("patch must be a non-empty object, e.g. {\"hp\": 5, \"inventory_add\": [\"odd book\"]}")
    engine.require_state()
    allowed = _NARRATIVE | _MERGE | _REPLACE | _HELPERS
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise GameError(f"cannot patch {unknown}; allowed keys: {sorted(allowed)} "
                        "(derived is recomputed; id/team_id are managed by the engine)")
    with engine.txn(f"character_update {char_id}"):
        st = engine.state
        c = find_char(st, char_id)
        warns = []
        for k, v in patch.items():
            if k in _HELPERS:
                continue
            if k == "attributes":
                if not isinstance(v, dict):
                    raise GameError("attributes patch must be an object")
                for ak, av in v.items():
                    a = rules.norm_attr(ak)
                    if a is None:
                        raise GameError(f"unknown attribute {ak!r}")
                    c["attributes"][a] = max(0, min(12, int(av)))
            elif k == "bp":
                if isinstance(v, int):
                    v = {"current": v}
                for bk, bv in v.items():
                    if bk not in ("current", "total"):
                        raise GameError("bp keys: current, total")
                    c["bp"][bk] = int(bv)
            elif k == "arc_abilities":
                for ak, av in v.items():
                    if ak not in rules.ARC_ABILITIES:
                        raise GameError(f"arc ability must be one of {rules.ARC_ABILITIES}")
                    c["arc_abilities"][ak] = bool(av)
            elif k == "bonds":
                for who, b in v.items():
                    o = find_char(st, who)
                    c["bonds"][o["id"]] = {**c["bonds"].get(o["id"], {}), **_norm_bond(b)} \
                        if isinstance(b, dict) else _norm_bond(b)
            elif k == "affinities":
                els = [rules.norm_element(e) for e in ([v] if isinstance(v, str) else v)]
                if None in els:
                    raise GameError(f"unknown element in {v!r}; valid: {rules.ELEMENTS}")
                c["affinities"] = els
            elif k == "arts":
                new = []
                for i, a in enumerate(v):
                    tags, errs = rules.norm_tags(a.get("tags"))
                    if errs:
                        raise GameError(f"art {i}: " + "; ".join(errs))
                    new.append({"name": str(a.get("name", f"Art {i + 1}")),
                                "description": str(a.get("description", "")), "tags": tags})
                c["arts"] = new
            elif k == "talents":
                w: list = []
                ti = Issues()
                new = []
                for r in v:
                    t = _resolve_talent(r, ti, w)
                    if t:
                        t.pop("_cat", None)
                        new.append(t)
                if ti.errors:
                    raise GameError("; ".join(ti.errors))
                warns += ti.warnings
                c["talents"] = new
            elif k == "field_skills":
                c["field_skills"] = [{"name": f, "description": ""} if isinstance(f, str) else
                                     {"name": str(f["name"]), "description": str(f.get("description", ""))}
                                     for f in v]
            elif k == "partner_ids":
                c["partner_ids"] = _resolve_refs(st, v)
            elif k == "role":
                if v not in ("bearer", "blade"):
                    raise GameError("role must be bearer or blade")
                c["role"] = v
            elif k == "controller":
                if v not in ("player", "architect"):
                    raise GameError("controller must be 'player' or 'architect'")
                c["controller"] = v
            elif k == "hp":
                c["hp"] = int(v)
            elif k == "dead":
                c["dead"] = bool(v)
            elif k == "inventory":
                c["inventory"] = [str(x) for x in v]
            elif k in ("basic_range_bonus",):
                c[k] = max(0, min(rules.MAX_BASIC_RANGE_BONUS, int(v)))
            elif k == "tag_refund_available":
                c[k] = bool(v)
            else:
                c[k] = str(v)
        for it in patch.get("inventory_add") or []:
            c["inventory"].append(str(it))
        for it in patch.get("inventory_remove") or []:
            if str(it) in c["inventory"]:
                c["inventory"].remove(str(it))
            else:
                warns.append(f"inventory item {it!r} not found")
        if "hp_delta" in patch:
            c["hp"] = int(c["hp"]) + int(patch["hp_delta"])
        mx_before = c["derived"].get("max_hp", 0)
        rules.recompute_derived(c)
        c["hp"] = max(0, min(int(c["hp"]), c["derived"]["max_hp"]))
        if "role" in patch or "partner_ids" in patch:
            wire_teams(st)
        r = {"ok": True, "character": digest(c)}
        if warns:
            r["warnings"] = warns
        return r


# --------------------------------------------------------------- advance
def _art_ref(c: dict, ref: Any) -> tuple[int, dict]:
    arts = c["arts"]
    if isinstance(ref, str) and ref.strip().lstrip("-").isdigit():
        ref = int(ref)
    if isinstance(ref, int):
        if 0 <= ref < len(arts):
            return ref, arts[ref]
        raise GameError(f"art index {ref} out of range; use 0-{len(arts) - 1}")
    for i, a in enumerate(arts):
        if slug(a["name"]) == slug(ref):
            return i, a
    raise GameError(f"no art {ref!r}; arts: {[(i, a['name']) for i, a in enumerate(arts)]} (index is 0-based)")


def _advance(engine: Engine, char_id: str, purchase: dict, force: bool = False) -> dict:
    if not isinstance(purchase, dict) or "type" not in purchase:
        raise GameError("purchase must be an object with 'type': attribute | affinity | field_skill | talent | "
                        "basic_range | art_tag | refund_tag | rename_art")
    engine.require_state()
    with engine.txn(f"advance {char_id} {purchase.get('type')}"):
        st = engine.state
        c = find_char(st, char_id)
        iss = Issues()
        typ = str(purchase["type"]).lower()
        cost = 0
        what = ""
        apply = lambda: None  # noqa: E731
        refund = False

        if typ == "attribute":
            a = rules.norm_attr(purchase.get("attribute"))
            if not a:
                raise GameError(f"purchase.attribute must be one of {ATTRIBUTES}")
            cur = c["attributes"][a]
            if rules.is_untouched(c) and a == "attunement":
                iss.rule("Untouched characters' attunement is permanently 0")
            if cur >= 12:
                iss.rule(f"{a} is already 12")
            new = cur + 1
            cost = 2 * new
            what = f"{a} {cur}->{new}"
            apply = lambda: c["attributes"].__setitem__(a, new)  # noqa: E731
        elif typ == "affinity":
            el = rules.norm_element(purchase.get("element"))
            if not el:
                raise GameError(f"purchase.element must be one of {rules.ELEMENTS}")
            if el in c["affinities"]:
                iss.rule(f"already has {el} affinity")
            if rules.is_untouched(c):
                iss.rule("Untouched characters cannot acquire affinities")
            new_total = len(c["affinities"]) + 1
            cost = 7 * new_total
            what = f"affinity {el} (#{new_total})"
            apply = lambda: c["affinities"].append(el)  # noqa: E731
        elif typ == "field_skill":
            nm = str(purchase.get("name", "")).strip()
            if not nm:
                raise GameError("purchase.name (the field skill) is required")
            if any(slug(f["name"]) == slug(nm) for f in c["field_skills"]):
                iss.rule(f"already has field skill {nm!r}")
            cost = 3
            what = f"field skill {nm}"
            apply = lambda: c["field_skills"].append(  # noqa: E731
                {"name": nm, "description": str(purchase.get("description", ""))})
        elif typ == "basic_range":
            bonus = c.get("basic_range_bonus", 0)
            if bonus >= rules.MAX_BASIC_RANGE_BONUS:
                iss.rule(f"basic range bonus is already the maximum ({rules.MAX_BASIC_RANGE_BONUS})")
            cost = 2 * (bonus + 1)
            what = f"basic range +{bonus}->+{bonus + 1}"
            apply = lambda: c.__setitem__("basic_range_bonus", bonus + 1)  # noqa: E731
        elif typ == "talent":
            cost, what, apply = _plan_talent(c, purchase, iss)
        elif typ == "art_tag":
            _, art = _art_ref(c, purchase.get("art"))
            tag = rules.norm_tag(purchase.get("tag"))
            if not tag:
                raise GameError(f"purchase.tag must be one of {list(TAGS)}")
            d = TAGS[tag]
            tags = art["tags"]
            if tags.get(tag, 0) >= d["max"]:
                iss.rule(f"{tag} is already at its max ({d['max']}) on {art['name']}")
            if c["role"] not in d["roles"]:
                iss.rule(f"{tag} is {'/'.join(d['roles'])}-only")
            if d["category"] == "elemental" and not rules.elemental_tag_ok(tag, c["affinities"]):
                iss.rule(f"{tag} requires a matching elemental affinity")
            if d["category"] not in ("fundamentals", "other"):
                others = [t for t in tags if TAGS[t]["category"] == d["category"] and t != tag]
                if others:
                    iss.rule(f"{art['name']} already has {others[0]} in category {d['category']}; "
                             "only one distinct tag per category (refund it at arc end to swap)")
            cost = rules.art_tag_bp_cost(tags, tag)
            what = f"{tag} on {art['name']} (now x{tags.get(tag, 0) + 1})"
            apply = lambda: tags.__setitem__(tag, tags.get(tag, 0) + 1)  # noqa: E731
        elif typ == "refund_tag":
            _, art = _art_ref(c, purchase.get("art"))
            tag = rules.norm_tag(purchase.get("tag"))
            if not tag or art["tags"].get(tag, 0) < 1:
                raise GameError(f"{art['name']} has no tag {purchase.get('tag')!r}; tags: {art['tags']}")
            if not c.get("tag_refund_available"):
                iss.rule("no tag refund available: one refund per arc, granted by arc_end")
            cost = rules.art_tag_refund(art["tags"], tag)
            refund = True
            what = f"refund {tag} on {art['name']}"
            tags = art["tags"]

            def apply():
                tags[tag] -= 1
                if tags[tag] <= 0:
                    del tags[tag]
                c["tag_refund_available"] = False
        elif typ == "rename_art":
            _, art = _art_ref(c, purchase.get("art"))
            nm = purchase.get("name")
            if not nm and "description" not in purchase:
                raise GameError("rename_art needs name and/or description")

            def apply():
                if nm:
                    art["name"] = str(nm)
                if "description" in purchase:
                    art["description"] = str(purchase["description"])
            what = f"rename art -> {nm or art['name']}"
            cost = 0
        else:
            raise GameError(f"unknown purchase type {typ!r}")

        if "cost" in purchase and purchase["cost"] is not None:
            cost = int(purchase["cost"])
            iss.warn(f"cost overridden by GM to {cost}")
        if not refund and cost > c["bp"]["current"]:
            iss.rule(f"costs {cost} BP but {c['name']} has {c['bp']['current']}")
        bad = _fail(iss, force)
        if bad:
            bad["cost"] = cost
            raise _Abort(bad)
        warnings = _forced_warnings(iss, force)
        apply()
        if refund:
            c["bp"]["current"] += cost
        else:
            c["bp"]["current"] = max(0, c["bp"]["current"] - cost)
        refresh(c)
        engine.log(f"{c['name']} {'regains' if refund else 'spends'} {cost} BP: {what}.", "bp")
        r = {"ok": True, "purchased": what, "cost": -cost if refund else cost, "bp": c["bp"],
             "character": digest(c)}
        if warnings:
            r["warnings"] = warnings
        return r


class _Abort(Exception):
    """Carries a failure result out of a txn (txn rolls back; nothing changed anyway)."""

    def __init__(self, result: dict):
        self.result = result


def character_advance(engine: Engine, char_id: str, purchase: dict, force: bool = False) -> dict:
    try:
        return _advance(engine, char_id, purchase, force)
    except _Abort as a:
        return a.result


def _plan_talent(c: dict, p: dict, iss: Issues):
    ref = p.get("talent") or p.get("id") or p.get("name")
    if not ref:
        raise GameError("purchase.talent (name or id) is required")
    cat = rules.talent_catalog()
    t = rules.find_talent(ref)
    if cat is not None and t is None:
        near = rules.search_talents(ref)
        raise GameError(f"unknown talent {ref!r}" + (f"; did you mean {near}?" if near else ""))
    owned = rules.char_talent(c, ref)
    if t is None:
        iss.warn("talent catalog missing: accepting talent verbatim")
        rank = int(p.get("rank", 1))
        lo = hi = rank
        tid, nm, per = slug(ref), str(ref), None
    else:
        lo, hi = rules.talent_rank_range(t)
        tid, nm, per = t["id"], t["name"], t.get("per")
        rank = int(p["rank"]) if p.get("rank") is not None else (lo if not owned else owned["rank"] + 1)
    if not lo <= rank <= hi:
        iss.rule(f"{nm} exists at rank {lo}" + (f"-{hi}" if hi != lo else "") + f", not {rank}")
    if owned:
        cur = int(owned["rank"])
        if rank <= cur:
            raise GameError(f"{c['name']} already has {nm} at rank {cur}; give purchase.rank above that to upgrade")
        if hi == lo:
            raise GameError(f"{nm} is not an upgradable talent and is already owned")
        cost = 3 * (rank - cur)
        what = f"{nm} rank {cur}->{rank}"

        def apply():
            owned["rank"] = rank
    else:
        if t is not None:
            attrs = c["attributes"]
            check_talent_prereqs(t, c["role"], attrs, rules.char_talent_ids(c), iss, creation=False)
            if t.get("category") == "archetype" and any(
                    (rules.find_talent(x["id"]) or {}).get("category") == "archetype" for x in c["talents"]):
                iss.rule("only one archetype talent is allowed")
        cost = 3 * rank
        what = f"talent {nm} rank {rank}"

        def apply():
            c["talents"].append({"id": tid, "name": nm, "rank": rank, "choice": str(p.get("choice", "")),
                                 "per": per, "used": False})
    return cost, what, apply


# ----------------------------------------------------- bonds & affinity
def bond_set(engine: Engine, from_id: str, to_id: str, name: str, benefit: str = "", drawback: str = "") -> dict:
    with engine.txn("bond_set"):
        st = engine.state
        a, b = find_char(st, from_id), find_char(st, to_id)
        if a["id"] == b["id"]:
            raise GameError("a bond needs two different characters")
        a["bonds"][b["id"]] = {"name": name, "benefit": benefit, "drawback": drawback}
        st["affinity"].setdefault(rules.pair_key(a["id"], b["id"]), 0)
        engine.log(f"Bond {a['name']} -> {b['name']}: {name}.", "system")
        return {"ok": True, "bond": {"from": a["id"], "to": b["id"], **a["bonds"][b["id"]]},
                "affinity": st["affinity"][rules.pair_key(a["id"], b["id"])]}


def affinity_set(engine: Engine, a: str, b: str, value: Optional[int] = None, delta: Optional[int] = None,
                 reason: str = "") -> dict:
    if value is None and delta is None:
        raise GameError("give value (absolute -2..2) or delta (relative)")
    with engine.txn("affinity_set"):
        st = engine.state
        ca, cb = find_char(st, a), find_char(st, b)
        if ca["id"] == cb["id"]:
            raise GameError("affinity is between two different characters")
        k = rules.pair_key(ca["id"], cb["id"])
        old = st["affinity"].get(k, 0)
        new = int(value) if value is not None else old + int(delta)
        new = max(-2, min(2, new))
        st["affinity"][k] = new
        if new != old:
            engine.log(f"Affinity {ca['name']}/{cb['name']}: {old:+d} -> {new:+d}" + (f" ({reason})" if reason else ""),
                       "system")
        return {"ok": True, "pair": k, "old": old, "affinity": new}


def grant_bp(engine: Engine, char_ids: list, amount: int, reason: str = "") -> dict:
    if isinstance(char_ids, str):
        char_ids = [char_ids]
    with engine.txn("grant_bp"):
        st = engine.state
        out = {}
        for r in char_ids:
            c = find_char(st, r)
            c["bp"]["current"] = max(0, c["bp"]["current"] + int(amount))
            if amount > 0:
                c["bp"]["total"] += int(amount)
            out[c["id"]] = c["bp"]["current"]
        engine.log(f"{amount:+d} BP to {', '.join(out)}" + (f": {reason}" if reason else ""), "bp")
        return {"ok": True, "bp": out}


# ----------------------------------------------------------------- rolls
def _require_session(st: dict, force: bool) -> None:
    if not st["clock"]["session_open"] and not force:
        raise GameError("no session is open: call session_begin first (or pass force=true)")


def _summary(who, label, attr, pool, rec):
    a = "+".join(attr) if isinstance(attr, list) else attr
    t = rec["tier"].upper() if rec.get("tier") else ""
    return (f"{who} {a or 'dice'} ({label}): pool {pool} {rec['dice']} -> {rec['successes']} succ "
            f"vs check {rec['check']} = net {rec['net']} {t}"
            + (f" [{dice.TIER_MEANING[rec['tier']]}]" if rec.get("tier") else ""))


def roll_check(engine: Engine, char_id: str, attribute: str = "", label: str = "", check: int = 0,
               modifier: int = 0, modifier_notes: str = "", helper_id: Optional[str] = None,
               extra_attributes: Optional[list] = None, use: Optional[str] = None, force: bool = False) -> dict:
    with engine.txn("roll_check"):
        st = engine.state
        _require_session(st, force)
        c = find_char(st, char_id)
        warnings = []
        if c.get("dead"):
            warnings.append(f"{c['name']} is marked dead")
        use = (use or "").strip().lower() or None
        if use not in (None, "reyn_time", "heronop"):
            raise GameError("use must be null, 'reyn_time' or 'heronop'")
        if use == "heronop":
            return _heronop(engine, c, force)
        a = rules.norm_attr(attribute)
        if not a:
            raise GameError(f"attribute required, one of {ATTRIBUTES}")
        if use == "reyn_time" and not c["arc_abilities"].get("reyn_time") and not force:
            raise GameError(f"{c['name']} has already used It's Reyn Time this arc (force=true to override)")
        mods, pool = [], c["attributes"][a]
        attrs = [a]
        for x in extra_attributes or []:
            xa = rules.norm_attr(x)
            if not xa:
                raise GameError(f"unknown extra attribute {x!r}")
            attrs.append(xa)
            pool += c["attributes"][xa]
            mods.append({"label": f"+{xa}", "value": c["attributes"][xa]})
        if helper_id:
            h = find_char(st, helper_id)
            aff = st["affinity"].get(rules.pair_key(c["id"], h["id"]), 0)
            if aff < 0 and rules.char_talent(c, "building_through_conflict"):
                aff = 0 if aff == -1 else -1
            if aff:
                mods.append({"label": f"affinity with {h['name']}", "value": aff})
                pool += aff
        if modifier:
            mods.append({"label": modifier_notes or "modifier", "value": int(modifier)})
            pool += int(modifier)
        floor = pool < 1
        rolled = engine.roller.roll(1 if floor else pool)
        rec_fields: dict[str, Any] = dict(
            who=c["name"], char_id=c["id"], label=label, kind="check",
            attribute=attrs if len(attrs) > 1 else a, pool=pool, mods=mods, dice=rolled, check=int(check))
        succ = dice.count_successes(rolled)
        net = succ - int(check)
        note = []
        if floor:
            rec_fields["pool_floor"] = True
            note.append("pool below 1: rolled 1 die; on failure another character is also affected")
        if use == "reyn_time":
            net = max(net, 2)
            rec_fields["auto"] = "reyn_time"
            c["arc_abilities"]["reyn_time"] = False
            note.append("It's Reyn Time: success guaranteed")
        rec_fields["net"] = net
        rec_fields["tier"] = dice.tier(net)
        rec_fields["base"] = c["attributes"][a]
        rec_fields["note"] = "; ".join(note)
        rec = engine.record_roll(**rec_fields)
        general = []
        for t in c["talents"]:
            ct = rules.find_talent(t["id"])
            if ct is None or ct.get("kind") != "combat":
                general.append(t["name"])
        r = {"ok": True, "roll": rec, "summary": _summary(c["name"], label, rec["attribute"], pool, rec),
             "reminders": {"field_skills": [f["name"] for f in c["field_skills"]], "talents": general,
                           "heronop_available": c["arc_abilities"].get("heronop", False),
                           "reyn_time_available": c["arc_abilities"].get("reyn_time", False)}}
        if warnings:
            r["warnings"] = warnings
        return r


def _heronop(engine: Engine, c: dict, force: bool) -> dict:
    st = engine.state
    if not c["arc_abilities"].get("heronop") and not force:
        raise GameError(f"{c['name']} has already used The Heronop Special this arc (force=true to override)")
    target = None
    for r in reversed(st["rolls"]):
        if r.get("char_id") == c["id"] and r.get("kind") == "check" and r.get("net") is not None and r["net"] < 0 \
                and r.get("auto") is None:
            target = r
            break
        if r.get("char_id") == c["id"] and r.get("kind") == "check":
            break
    if target is None:
        raise GameError(f"{c['name']}'s most recent check is not a failure that can be turned into a near miss")
    target["net"] = 0
    target["tier"] = "near_miss"
    target["auto"] = "heronop"
    target["note"] = (target.get("note", "") + "; Heronop Special: failure became a near miss").lstrip("; ")
    c["arc_abilities"]["heronop"] = False
    engine.log(f"{c['name']} uses The Heronop Special: '{target['label']}' becomes a near miss.", "system")
    return {"ok": True, "roll": target, "summary": f"{c['name']}: failed roll '{target['label']}' is now a NEAR MISS "
            f"({dice.TIER_MEANING['near_miss']})"}


def roll_dice(engine: Engine, n: int, label: str = "", who: str = "Architect") -> dict:
    n = int(n)
    if n < 0 or n > 60:
        raise GameError("n must be between 0 and 60")
    with engine.txn("roll_dice"):
        rolled = engine.roller.roll(n)
        rec = engine.record_roll(who=who, label=label, kind="raw", pool=n, dice=rolled)
        return {"ok": True, "roll": rec,
                "summary": f"{who} rolls {n}d6 {rolled}: {rec['successes']} success(es) (5-6). {label}"}


def reconciliation_burst(engine: Engine, a: str, b: str, mode: str = "check", attributes_a: Optional[list] = None,
                         attributes_b: Optional[list] = None, label: str = "", check: int = 0,
                         modifier: int = 0, modifier_notes: str = "", force: bool = False) -> dict:
    if mode != "check":
        raise GameError("in combat use combat_special(..., free_burst=true); this tool is for out-of-combat checks")
    with engine.txn("reconciliation_burst"):
        st = engine.state
        _require_session(st, force)
        ca, cb = find_char(st, a), find_char(st, b)
        k = rules.pair_key(ca["id"], cb["id"])
        aff = st["affinity"].get(k, 0)
        if aff >= 0 and not force:
            raise GameError(f"reconciliation bursts need negative affinity (currently {aff:+d})")
        need = 2 if aff <= -2 else 1
        la = [rules.norm_attr(x) for x in (attributes_a or [])]
        lb = [rules.norm_attr(x) for x in (attributes_b or [])]
        if None in la or None in lb or len(la) != need or len(lb) != need:
            raise GameError(f"at affinity {aff:+d} each character contributes {need} attribute(s): pass "
                            f"attributes_a and attributes_b as lists of exactly {need} attribute name(s)")
        pool = sum(ca["attributes"][x] for x in la) + sum(cb["attributes"][x] for x in lb) + int(modifier)
        mods = [{"label": f"{ca['name']} {'+'.join(la)}", "value": sum(ca["attributes"][x] for x in la)},
                {"label": f"{cb['name']} {'+'.join(lb)}", "value": sum(cb["attributes"][x] for x in lb)}]
        if modifier:
            mods.append({"label": modifier_notes or "modifier", "value": int(modifier)})
        floor = pool < 1
        rolled = engine.roller.roll(1 if floor else pool)
        net = dice.count_successes(rolled) - int(check)
        rec = engine.record_roll(who=f"{ca['name']} & {cb['name']}", char_id=ca["id"],
                                 label=label or "reconciliation burst", kind="check", attribute=la + lb,
                                 pool=pool, mods=mods, dice=rolled, check=int(check), net=net,
                                 note="reconciliation burst" + ("; pool floor" if floor else ""))
        st["affinity"][k] = 0
        engine.log(f"Reconciliation burst between {ca['name']} and {cb['name']}: affinity {aff:+d} -> 0.", "system")
        return {"ok": True, "roll": rec, "summary": _summary(f"{ca['name']}&{cb['name']}", label, la + lb, pool, rec),
                "affinity": 0}


def use_ability(engine: Engine, char_id: str, ability: str, undo_use: bool = False) -> dict:
    with engine.txn("use_ability"):
        st = engine.state
        c = find_char(st, char_id)
        ab = slug(ability)
        if ab in rules.ARC_ABILITIES:
            c["arc_abilities"][ab] = bool(undo_use)
            return {"ok": True, "character": c["id"], "ability": ab,
                    "available": c["arc_abilities"][ab]}
        t = rules.char_talent(c, ability)
        if not t:
            raise GameError(f"{c['name']} has no ability/talent {ability!r}; arc abilities: "
                            f"{list(rules.ARC_ABILITIES)}; talents: {[x['name'] for x in c['talents']]}")
        if not t.get("per"):
            raise GameError(f"talent {t['name']} is not limited-use (no per-arc/session/combat limit)")
        if not undo_use and t.get("used"):
            raise GameError(f"{t['name']} already used this {t['per']}")
        t["used"] = not undo_use
        return {"ok": True, "character": c["id"], "ability": t["name"], "per": t["per"], "used": t["used"]}
