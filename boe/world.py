"""World: campaigns, sessions/arcs, state queries, scene, entities, journal, recall."""
from __future__ import annotations

import copy
from typing import Any, Optional

from . import characters as ch
from . import reference, rules
from .engine import Engine, GameError, now_iso
from .rules import slug

ENTITY_KINDS = ("npc", "location", "titan", "faction", "thread", "item", "secret", "other")
CLOSED = {"closed", "resolved", "done", "complete", "completed", "abandoned", "dead", "destroyed"}


# -------------------------------------------------------------- campaigns
def campaign_list(engine: Engine) -> dict:
    return {"ok": True, "campaigns": engine.list_campaigns(),
            "active": engine.state["meta"]["slug"] if engine.state else None}


def campaign_create(engine: Engine, name: str, starting_point: str, premise: str = "", tone: str = "",
                    safety: Optional[list] = None, player_name: str = "") -> dict:
    if not str(name).strip():
        raise GameError("campaign name required")
    sp = rules.norm_starting_point(starting_point)
    if not sp:
        raise GameError(f"starting_point must be one of {list(rules.STARTING_POINTS)}")
    st = engine.create_campaign(str(name).strip(), sp, premise=premise, tone=tone,
                                safety=list(safety or []), player_name=player_name)
    b = rules.STARTING_POINTS[sp]
    return {"ok": True, "slug": st["meta"]["slug"], "starting_point": sp, "budgets": b, "ui": engine.ui_url,
            "next": "Create the player's character and partner with character_create (see creation_options), "
                    "set bonds with bond_set, then call session_begin."}


def campaign_load(engine: Engine, slug_: str) -> dict:
    st = engine.load_campaign(slug_)
    return {"ok": True, "slug": st["meta"]["slug"], "name": st["meta"]["name"], "clock": st["clock"],
            "characters": [c["name"] for c in st["characters"].values()], "next": "Call session_begin."}


def campaign_rename(engine: Engine, name: str, rename_folder: bool = False) -> dict:
    r = engine.rename_campaign(name, bool(rename_folder))
    if not r["renamed"] and not r["folder_moved"]:
        r["note"] = "The campaign already has that title; nothing changed."
    else:
        r["note"] = ("Renamed. Everything else (characters, bonds, BP, NPCs, journal, recaps, combat, undo history) "
                     "is untouched" + ("; the save folder was renamed to match." if r["folder_moved"] else "."))
    return {"ok": True, **r}


def house_rule_add(engine: Engine, text: str) -> dict:
    if not str(text).strip():
        raise GameError("text required")
    with engine.txn("house_rule_add"):
        engine.state["meta"]["house_rules"].append(str(text).strip())
        engine.log(f"House rule: {text}", "system")
        return {"ok": True, "house_rules": engine.state["meta"]["house_rules"]}


# --------------------------------------------------------------- sessions
def _party_line(c: dict) -> dict:
    d = c["derived"]
    attrs = " ".join(f"{a[:3]}{c['attributes'][a]}" for a in rules.ATTRIBUTES)
    return {
        "id": c["id"], "name": c["name"], "pronouns": c.get("pronouns", ""), "role": c["role"],
        "controller": c["controller"], "hp": f"{c['hp']}/{d['max_hp']}", "bp": c["bp"]["current"],
        "attrs": attrs, "affinities": c["affinities"], "weapon": c.get("weapon", ""),
        "field_skills": [f["name"] for f in c["field_skills"]],
        "arts": [{"i": i, "name": a["name"], "tags": a["tags"]} for i, a in enumerate(c["arts"])],
        "talents": [ch.talent_label(t) + (" [used]" if t.get("used") else "") for t in c["talents"]],
        "arc_abilities": [k for k, v in c["arc_abilities"].items() if v],
        "derived": {k: d[k] for k in ("initiative_pool", "movement", "basic_range", "max_radius", "start_cooldowns")},
        "partners": c.get("partner_ids", []), "bonds": {k: v for k, v in c.get("bonds", {}).items()},
        "inventory": c.get("inventory", []), "tag_refund_available": c.get("tag_refund_available", False),
        **({"dead": True} if c.get("dead") else {}),
    }


def _combat_brief(st: dict) -> Optional[dict]:
    cb = st.get("combat")
    if not cb:
        return None
    cur = cb["order"][0] if cb.get("order") else None
    return {"name": cb.get("name"), "turns_taken": cb.get("turns_taken"),
            "current_actor": cb["combatants"][cur]["name"] if cur in cb["combatants"] else None,
            "combatants": [f"{c['name']} {c['hp']}/{c['max_hp']}{' DOWN' if c.get('down') else ''}"
                           for c in cb["combatants"].values()],
            "pending": cb.get("pending"), "hint": "call combat_state for the full digest"}


def _entity_brief(e: dict) -> str:
    s = e["name"] + (f" [{e['kind']}]" if e["kind"] != "npc" else "")
    if e.get("status"):
        s += f" ({e['status']})"
    if e.get("gm_only"):
        s += " {gm}"
    if e.get("summary"):
        s += ": " + e["summary"][:90]
    return s


def briefing(engine: Engine) -> dict:
    st = engine.require_state()
    m, clk = st["meta"], st["clock"]
    recaps = [{"session": s["n"], "arc": s["arc"], "summary": s["summary"]}
              for s in st["sessions"] if s.get("summary")][-2:]
    ents = [e for e in st["entities"].values() if e["kind"] != "thread" and e.get("status", "").lower() not in CLOSED]
    threads = [e for e in st["entities"].values() if e["kind"] == "thread"
               and e.get("status", "").lower() not in CLOSED]
    aff = {}
    for k, v in st["affinity"].items():
        a, b = k.split("|")
        na = st["characters"].get(a, {}).get("name", a)
        nb = st["characters"].get(b, {}).get("name", b)
        aff[f"{na} / {nb}"] = v
    out: dict[str, Any] = {
        "ok": True,
        "gm_guide": reference.core_guide_text() or "(gm_guide.md not built yet; call rules_lookup when unsure)",
        "gm_guide_more": [s["title"] for s in (reference.guide() or {"sections": []})["sections"] if not s["core"]],
        "campaign": {"slug": m["slug"], "name": m["name"], "starting_point": m["starting_point"],
                     "premise": m["premise"], "tone": m["tone"], "safety": m["safety"],
                     "player": m["player_name"], "house_rules": m["house_rules"]},
        "clock": clk,
        "arc": {"n": clk["arc"], "title": clk["arc_title"],
                "previous": [{"n": a["n"], "title": a["title"], "summary": a["summary"]} for a in st["arcs"][-2:]]},
        "recent_recaps": recaps,
        "recent_journal": [
            {"id": j["id"], "session": j["session"], "kind": j["kind"], "text": j["text"][:240],
             **({"gm_only": True} if j.get("gm_only") else {})}
            for j in [j for j in st["journal"] if j["kind"] not in ("system", "recap", "bp")][-8:]],
        "scene": st["scene"],
        "party": [_party_line(c) for c in st["characters"].values()],
        "teams": st["teams"], "affinity": aff,
        "open_threads": [_entity_brief(e) for e in threads],
        "world": [_entity_brief(e) for e in ents][:60],
        "combat": _combat_brief(st),
        "ui_url": engine.ui_url,
    }
    if not st["characters"]:
        out["next"] = "No characters yet: use creation_options then character_create."
    return out


def session_begin(engine: Engine) -> dict:
    with engine.txn("session_begin"):
        st = engine.state
        clk = st["clock"]
        resumed = clk["session_open"]
        if not resumed:
            clk["session"] += 1
            clk["session_open"] = True
            st["sessions"].append({"n": clk["session"], "arc": clk["arc"], "started": now_iso(),
                                   "ended": None, "summary": "", "bp_awards": []})
            for c in st["characters"].values():
                for t in c["talents"]:
                    if t.get("per") == "session":
                        t["used"] = False
            engine.log(f"Session {clk['session']} begins.", "system")
        b = briefing(engine)
        b["resumed_open_session"] = resumed
        return b


def _partner_pair(a: dict, b: dict) -> bool:
    return b["id"] in a.get("partner_ids", []) or a["id"] in b.get("partner_ids", [])


def session_end(engine: Engine, summary: str, bond_awards: Optional[list] = None,
                bond_updates: Optional[list] = None, affinity_changes: Optional[list] = None,
                attended: Optional[list] = None) -> dict:
    if not str(summary).strip():
        raise GameError("summary required: a few sentences recapping what happened (it is shown at the next session_begin)")
    with engine.txn("session_end"):
        st = engine.state
        clk = st["clock"]
        if not clk["session_open"]:
            raise GameError("no session is open")
        chars = st["characters"]
        att = [ch.find_char(st, a) for a in attended] if attended else \
            [c for c in chars.values() if not c.get("dead")]
        att_ids = {c["id"] for c in att}
        gains: dict[str, int] = {c["id"]: 1 for c in att}
        reasons: dict[str, list] = {c["id"]: ["attended"] for c in att}
        warnings, seen_pairs, partner_bonus = [], set(), set()
        for aw in bond_awards or []:
            a, b = ch.find_char(st, aw.get("a")), ch.find_char(st, aw.get("b"))
            pk = rules.pair_key(a["id"], b["id"])
            if pk in seen_pairs:
                warnings.append(f"duplicate bond award for {pk} ignored")
                continue
            seen_pairs.add(pk)
            why = str(aw.get("reason", "bond"))
            partners = _partner_pair(a, b)
            for x, y in ((a, b), (b, a)):
                if x["id"] not in att_ids:
                    warnings.append(f"{x['name']} did not attend; no BP for bond {pk}")
                    continue
                gains[x["id"]] += 1
                reasons[x["id"]].append(f"bond with {y['name']}: {why}")
                if partners:
                    if x["role"] == "bearer" and x["id"] in partner_bonus:
                        continue  # a Bearer with two Blades gets the partner bonus once per session
                    partner_bonus.add(x["id"])
                    gains[x["id"]] += 1
                    reasons[x["id"]].append("partner bonus")
        for u in bond_updates or []:
            a, b = ch.find_char(st, u.get("from")), ch.find_char(st, u.get("to"))
            old = a["bonds"].get(b["id"], {"name": "", "benefit": "", "drawback": ""})
            a["bonds"][b["id"]] = {k: str(u.get(k, old.get(k, ""))) for k in ("name", "benefit", "drawback")}
            st["affinity"].setdefault(rules.pair_key(a["id"], b["id"]), 0)
        for af in affinity_changes or []:
            ch_a, ch_b = ch.find_char(st, af.get("a")), ch.find_char(st, af.get("b"))
            k = rules.pair_key(ch_a["id"], ch_b["id"])
            old = st["affinity"].get(k, 0)
            new = int(af["value"]) if af.get("value") is not None else old + int(af.get("delta", 0))
            st["affinity"][k] = max(-2, min(2, new))
        awards = []
        for cid, n in gains.items():
            c = chars[cid]
            c["bp"]["current"] += n
            c["bp"]["total"] += n
            awards.append({"char_id": cid, "amount": n, "reasons": reasons[cid]})
        sess = st["sessions"][-1] if st["sessions"] else None
        if sess is None or sess.get("ended"):
            sess = {"n": clk["session"], "arc": clk["arc"], "started": now_iso(), "ended": None,
                    "summary": "", "bp_awards": []}
            st["sessions"].append(sess)
        sess.update(ended=now_iso(), summary=str(summary).strip(), bp_awards=awards)
        clk["session_open"] = False
        engine.log(f"Session {clk['session']} recap: {summary}", "recap")
        engine.log("BP awarded: " + ", ".join(f"{chars[a['char_id']]['name']} +{a['amount']}" for a in awards), "bp")
        r = {"ok": True, "session": clk["session"], "bp_awards": awards,
             "bp": {c["name"]: c["bp"]["current"] for c in chars.values()}}
        if warnings:
            r["warnings"] = warnings
        r["next"] = "Players may now spend BP with character_advance (between sessions). Call arc_end if the arc concluded."
        return r


def arc_end(engine: Engine, title: str, summary: str, next_arc_title: str = "") -> dict:
    with engine.txn("arc_end"):
        st = engine.state
        clk = st["clock"]
        warnings = []
        if clk["session_open"]:
            warnings.append("a session is still open; call session_end for BP first if you have not")
        sessions = [s["n"] for s in st["sessions"] if s["arc"] == clk["arc"]]
        st["arcs"].append({"n": clk["arc"], "title": title or clk["arc_title"], "summary": summary,
                           "first_session": min(sessions) if sessions else clk["session"],
                           "last_session": max(sessions) if sessions else clk["session"]})
        for c in st["characters"].values():
            c["arc_abilities"] = {k: True for k in rules.ARC_ABILITIES}
            c["tag_refund_available"] = True
            for t in c["talents"]:
                if t.get("per") == "arc":
                    t["used"] = False
        engine.log(f"Arc {clk['arc']} ends: {title}. {summary}", "recap")
        clk["arc"] += 1
        clk["arc_title"] = next_arc_title
        r = {"ok": True, "arc_ended": st["arcs"][-1], "new_arc": clk["arc"],
             "reset": "arc abilities and per-arc talents refreshed; each PC may refund one art tag "
                      "(character_advance type=refund_tag)"}
        if warnings:
            r["warnings"] = warnings
        return r


# ------------------------------------------------------------------ state
def get_state(engine: Engine, scope: str = "summary") -> dict:
    st = engine.require_state()
    scope = (scope or "summary").strip()
    if scope == "summary":
        return {"ok": True, "version": st["version"], "campaign": st["meta"]["name"], "clock": st["clock"],
                "scene": st["scene"], "party": [ch.digest(c, brief=True) for c in st["characters"].values()],
                "combat": _combat_brief(st),
                "counts": {"entities": len(st["entities"]), "journal": len(st["journal"])}}
    if scope == "party":
        return {"ok": True, "party": [_party_line(c) for c in st["characters"].values()],
                "teams": st["teams"], "affinity": st["affinity"]}
    if scope.startswith("character:"):
        c = ch.find_char(st, scope.split(":", 1)[1])
        return {"ok": True, "character": c}
    if scope == "world":
        return {"ok": True, "entities": [{k: e[k] for k in ("id", "kind", "name", "summary", "status", "gm_only")}
                                         for e in st["entities"].values()]}
    if scope.startswith("journal"):
        n = 15
        if ":" in scope:
            try:
                n = max(1, min(200, int(scope.split(":", 1)[1])))
            except ValueError:
                raise GameError("use journal:<n> with a number, e.g. journal:20")
        return {"ok": True, "journal": st["journal"][-n:]}
    if scope == "combat":
        from . import combat as _combat
        return _combat.combat_state(engine)
    if scope == "full":
        return {"ok": True, "state": st}
    raise GameError("scope must be summary | party | character:<id> | world | journal:<n> | combat | full")


# ------------------------------------------------------------------ scene
def scene_set(engine: Engine, title: str, location: str = "", description: str = "",
              present: Optional[list] = None, mood: str = "") -> dict:
    with engine.txn("scene_set"):
        st = engine.state
        st["scene"] = {"title": title, "location": location, "description": description,
                       "present": [str(p) for p in (present or [])], "mood": mood}
        return {"ok": True, "scene": st["scene"]}


# --------------------------------------------------------------- entities
def normalize_card(card: Any) -> dict:
    if isinstance(card, str):
        e = reference.bestiary(card)
        if e is None:
            raise GameError(f"no bestiary entry {card!r} (or bestiary not built yet); pass a full card object")
        card = {k: v for k, v in e.items() if k not in ("id", "name")}
    if not isinstance(card, dict):
        raise GameError("card must be an object or a bestiary id")

    def triple(v, default):
        v = v if isinstance(v, dict) else {}
        try:
            return {k: int(v.get(k, default[k])) for k in ("dis", "normal", "adv")}
        except (TypeError, ValueError):
            raise GameError("card attack/defense values must be integers: {dis, normal, adv}")
    try:
        return {
            "role": card.get("role", "other"),
            "attack": triple(card.get("attack"), {"dis": 1, "normal": 2, "adv": 3}),
            "defense": triple(card.get("defense"), {"dis": 0, "normal": 1, "adv": 2}),
            "hp": int(card.get("hp", 5)), "movement": int(card.get("movement", 3)),
            "initiative": int(card.get("initiative", 3)),
            "range": max(1, int(card.get("range", 1))),
            "affinities": list(card.get("affinities", [])),
            "best_attributes": list(card.get("best_attributes", [])),
            "art_tags": list(card.get("art_tags", [])),
            "special_abilities": list(card.get("special_abilities", [])),
            "notes": str(card.get("notes", "")),
        }
    except (TypeError, ValueError) as e:
        raise GameError(f"bad NPC card: {e}")


def find_entity(st: dict, ref: Any, required: bool = True) -> Optional[dict]:
    ents = st["entities"]
    if ref in ents:
        return ents[ref]
    s = slug(ref)
    for e in ents.values():
        if slug(e["id"]) == s or slug(e["name"]) == s:
            return e
    part = [e for e in ents.values() if s and s in slug(e["name"])]
    if len(part) == 1:
        return part[0]
    if required:
        raise GameError(f"no entity {ref!r}" + (f"; ambiguous: {[e['name'] for e in part]}" if part else ""))
    return None


def entity_upsert(engine: Engine, kind: str, name: str, summary: Optional[str] = None,
                  details: Optional[str] = None, tags: Optional[list] = None, status: Optional[str] = None,
                  gm_only: Optional[bool] = None, gm_notes: Optional[str] = None, card: Any = None) -> dict:
    kind = str(kind).lower()
    if kind not in ENTITY_KINDS:
        raise GameError(f"kind must be one of {list(ENTITY_KINDS)}")
    if not str(name).strip():
        raise GameError("name required")
    card_n = normalize_card(card) if card else None
    with engine.txn("entity_upsert"):
        st = engine.state
        e = find_entity(st, name, required=False)
        created = e is None
        if created:
            eid = slug(name).replace("_", "-") or "entity"
            base, n = eid, 2
            while eid in st["entities"]:
                eid, n = f"{base}-{n}", n + 1
            e = {"id": eid, "kind": kind, "name": str(name).strip(), "summary": "", "details": "", "tags": [],
                 "status": "", "gm_only": kind == "secret", "gm_notes": "", "card": None, "updated_session": 0}
            st["entities"][eid] = e
        e["kind"] = kind
        for k, v in (("summary", summary), ("details", details), ("status", status), ("gm_notes", gm_notes)):
            if v is not None:
                e[k] = str(v)
        if tags is not None:
            e["tags"] = [str(t) for t in tags]
        if gm_only is not None:
            e["gm_only"] = bool(gm_only)
        if card_n is not None:
            e["card"] = card_n
        e["updated_session"] = st["clock"]["session"]
        return {"ok": True, "created": created, "entity": e}


def entity_get(engine: Engine, name_or_id: str) -> dict:
    return {"ok": True, "entity": find_entity(engine.require_state(), name_or_id)}


def entity_list(engine: Engine, kind: str = "", include_gm: bool = True) -> dict:
    st = engine.require_state()
    rows = [e for e in st["entities"].values() if (not kind or e["kind"] == kind)
            and (include_gm or not e.get("gm_only"))]
    return {"ok": True, "count": len(rows), "entities": [
        {"id": e["id"], "kind": e["kind"], "name": e["name"], "status": e.get("status", ""),
         "summary": e.get("summary", "")[:120], "gm_only": e.get("gm_only", False),
         "has_card": bool(e.get("card"))} for e in rows]}


def entity_delete(engine: Engine, name_or_id: str) -> dict:
    with engine.txn("entity_delete"):
        e = find_entity(engine.state, name_or_id)
        del engine.state["entities"][e["id"]]
        return {"ok": True, "deleted": e["name"]}


# ---------------------------------------------------------------- journal
def journal_add(engine: Engine, text: str, kind: str = "event", tags: Optional[list] = None,
                gm_only: bool = False) -> dict:
    if kind not in ("event", "note", "recap", "system", "bp"):
        raise GameError("kind must be event | note | recap | system | bp")
    if not str(text).strip():
        raise GameError("text required")
    e = engine.log(str(text).strip(), kind, tags or (), gm_only)
    return {"ok": True, "entry": e}


def recall(engine: Engine, query: str, limit: int = 8) -> dict:
    st = engine.require_state()
    docs, meta = [], []
    for j in st["journal"]:
        docs.append(f"{j['text']} {' '.join(j.get('tags', []))}")
        meta.append(("journal", j, j["ts"]))
    for e in st["entities"].values():
        docs.append(f"{e['name']} {e['name']} {e['summary']} {e['details']} {e['gm_notes']} {' '.join(e['tags'])}")
        meta.append(("entity", e, ""))
    for s in st["sessions"]:
        if s.get("summary"):
            docs.append(s["summary"])
            meta.append(("session", s, s.get("ended") or ""))
    for a in st["arcs"]:
        docs.append(f"{a['title']} {a['summary']}")
        meta.append(("arc", a, ""))
    ranked = reference.bm25_rank(query, docs)
    # most relevant first; near-equal scores prefer the most recent (higher index)
    top = sorted(ranked, key=lambda x: (-round(x[1], 1), -x[0]))[:max(1, int(limit))]
    out = []
    for i, sc in top:
        kind, obj, _ = meta[i]
        if kind == "journal":
            row = {"type": "journal", "id": obj["id"], "session": obj["session"], "kind": obj["kind"],
                   "text": obj["text"], **({"gm_only": True} if obj["gm_only"] else {})}
        elif kind == "entity":
            row = {"type": "entity", "id": obj["id"], "kind": obj["kind"], "name": obj["name"],
                   "status": obj["status"], "summary": obj["summary"], "details": obj["details"][:400],
                   **({"gm_notes": obj["gm_notes"]} if obj["gm_notes"] else {})}
        elif kind == "session":
            row = {"type": "session_recap", "session": obj["n"], "summary": obj["summary"]}
        else:
            row = {"type": "arc", "n": obj["n"], "title": obj["title"], "summary": obj["summary"]}
        out.append(row)
    return {"ok": True, "results": out}


def undo(engine: Engine, steps: int = 1) -> dict:
    r = engine.undo(steps)
    return {"ok": True, **r}
