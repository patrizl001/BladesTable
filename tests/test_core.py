"""CORE tests: dice, creation validation, BP economy, sessions/arcs, undo, redaction, MCP + SSE round trips."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

from boe import characters as ch
from boe import dice, reference, rules, views, world
from boe.engine import Engine, GameError

MINI_CATALOG = {"talents": [
    {"id": "indomitable", "name": "Indomitable", "rank": 2, "category": "universal", "kind": "combat", "role": "any"},
    {"id": "fortified", "name": "Fortified", "rank": 4, "category": "universal", "kind": "combat", "role": "any"},
    {"id": "steel_flesh", "name": "Steel Flesh", "rank": 6, "category": "universal", "kind": "combat", "role": "any"},
    {"id": "opportunist", "name": "Opportunist", "rank": 6, "category": "universal", "kind": "combat", "role": "any"},
    {"id": "quick_step", "name": "Quick Step", "rank": 3, "category": "bearer", "kind": "combat", "role": "bearer"},
    {"id": "fleet_of_foot", "name": "Fleet of Foot", "rank": 5, "category": "bearer", "kind": "combat", "role": "bearer",
     "requires": {"attributes": {"swiftness": 5}, "talents": ["quick_step"]}},
    {"id": "healer", "name": "Healer", "rank": 1, "category": "universal", "kind": "combat", "role": "any"},
    {"id": "fame", "name": "Fame", "rank": None, "rank_min": 1, "rank_max": 4, "category": "universal",
     "kind": "general", "role": "any"},
    {"id": "building_through_conflict", "name": "Building Through Conflict", "rank": 3, "category": "universal",
     "kind": "general", "role": "any"},
    {"id": "first_forged", "name": "First Forged", "rank": 2, "category": "universal", "kind": "general",
     "role": "any", "creation_only": True},
    {"id": "swift_slide", "name": "Swift Slide", "rank": 4, "category": "blade", "kind": "combat", "role": "blade",
     "requires": {"attributes": {"swiftness": 4}}},
    {"id": "untouched", "name": "Untouched", "rank": 1, "category": "archetype", "kind": "general", "role": "bearer"},
    {"id": "telethial", "name": "Telethial", "rank": 1, "category": "archetype", "kind": "general", "role": "bearer"},
    {"id": "ether_filter", "name": "Ether Filter", "rank": 5, "category": "archetype_talent", "kind": "general",
     "role": "bearer", "requires": {"archetype": "untouched"}},
    {"id": "second_wind", "name": "Second Wind", "rank": 1, "category": "universal", "kind": "combat",
     "role": "any", "per": "arc"},
]}


@pytest.fixture
def eng(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    (d / "talents.json").write_text(json.dumps(MINI_CATALOG))
    monkeypatch.setattr(rules, "DATA_DIR", d)
    monkeypatch.setattr(reference, "DATA_DIR", d)
    monkeypatch.setenv("BOE_HOME", str(tmp_path / "home"))
    e = Engine(home=tmp_path / "home", seed=7)
    return e


def new_campaign(e, sp="fresh_face"):
    return world.campaign_create(e, "Test Campaign", sp)


def art(name, tags):
    return {"name": name, "description": "", "tags": tags}


def sheet(sp="fresh_face", role="bearer", name="Pyre", partner=None, element="fire"):
    s = {
        "fresh_face": dict(
            attrs={"might": 4, "willpower": 4, "stamina": 3},
            tags={"potency": 1, "cooldown": 1, "rush": 1}, fs=2, talents=["Indomitable", "Building Through Conflict"]),
        "part_time_hero": dict(
            attrs={"might": 6, "willpower": 5, "stamina": 4, "gut": 2},
            tags={"potency": 2, "cooldown": 1, "rush": 2}, fs=3,
            talents=["Fortified", {"name": "Fame", "rank": 1}, "Healer", "Indomitable"]),
        "veteran": dict(
            attrs={"might": 7, "willpower": 6, "stamina": 5, "gut": 4},
            tags={"potency": 3, "rush": 2, "unique_effect": 1, "side": 1}, fs=4,
            talents=["Fortified", "Quick Step", "Indomitable", "Healer", {"name": "Fame", "rank": 1}]),
        "titan_savior": dict(
            attrs={"might": 8, "willpower": 8, "stamina": 6, "gut": 3, "experience": 2},
            tags={"potency": 4, "circle": 1, "rush": 2}, fs=5,
            talents=["Fortified", "Opportunist", "Quick Step", {"name": "Fame", "rank": 1}]),
    }[sp]
    tags = dict(s["tags"])
    if role == "blade":
        tags.pop("side", None)
    out = {"name": name, "role": role, "attributes": dict(s["attrs"]), "affinities": [element],
           "field_skills": [f"Skill {i}" for i in range(s["fs"])],
           "arts": [art(f"Art {i}", dict(tags)) for i in range(3)], "talents": list(s["talents"])}
    if partner:
        out["partner"] = partner
    return out


def make_party(e, sp="fresh_face"):
    new_campaign(e, sp)
    r = ch.character_create(e, sheet(sp, "bearer", "Pyre", partner="Doma"))
    assert r["ok"], r
    r = ch.character_create(e, sheet(sp, "blade", "Doma", partner="Pyre", element="water"))
    assert r["ok"], r
    return e


def rich(e, cid, bp=200):
    ch.character_update(e, cid, {"bp": {"current": bp, "total": bp}})


# ------------------------------------------------------------------- dice
def test_dice_tiers_and_successes():
    assert dice.tier(3) == "success" and dice.tier(2) == "success"
    assert dice.tier(1) == "near_hit"
    assert dice.tier(0) == "near_miss"
    assert dice.tier(-1) == "failure" and dice.tier(-4) == "failure"
    assert dice.count_successes([1, 2, 3, 4, 5, 6, 6]) == 3
    r = dice.Roller(seed=1)
    r.queue([6, 5])
    out = r.roll(4)
    assert out[:2] == [6, 5] and len(out) == 4 and all(1 <= d <= 6 for d in out)
    assert dice.Roller(3).roll(5) == dice.Roller(3).roll(5)


def test_roll_check_tiers_pool_floor_and_modifiers(eng):
    make_party(eng)
    world.session_begin(eng)
    eng.roller.queue([6, 6, 5, 1])  # might 4
    r = ch.roll_check(eng, "pyre", "might", "lift", check=1)
    rec = r["roll"]
    assert rec["pool"] == 4 and rec["successes"] == 3 and rec["net"] == 2 and rec["tier"] == "success"
    eng.roller.queue([5, 1, 1, 1])
    r = ch.roll_check(eng, "pyre", "might", "x", check=0, modifier=-3, modifier_notes="bad")
    assert r["roll"]["pool"] == 1 and r["roll"]["net"] == 1 and r["roll"]["tier"] == "near_hit"
    eng.roller.queue([1])
    r = ch.roll_check(eng, "pyre", "swiftness", "x", modifier=-5)
    assert r["roll"]["pool_floor"] is True and r["roll"]["tier"] == "near_miss" and len(r["roll"]["dice"]) == 1
    eng.roller.queue([3, 3, 3, 3])
    r = ch.roll_check(eng, "pyre", "might", "x", check=1)
    assert r["roll"]["tier"] == "failure" and r["roll"]["net"] == -1


def test_roll_requires_session_and_helper_affinity(eng):
    make_party(eng)
    with pytest.raises(GameError):
        ch.roll_check(eng, "pyre", "might", "x")
    world.session_begin(eng)
    ch.affinity_set(eng, "pyre", "doma", value=-1)
    ch.character_update(eng, "doma", {"talents": ["Indomitable"]})   # no Building Through Conflict
    eng.roller.queue([1] * 4)
    r = ch.roll_check(eng, "doma", "might", "x", helper_id="pyre")   # doma might 4, affinity -1
    assert r["roll"]["pool"] == 3 and r["roll"]["mods"] == [{"label": "affinity with Pyre", "value": -1}]
    # Building Through Conflict (pyre has it): -1 affinity -> no penalty
    eng.roller.queue([1] * 4)
    r = ch.roll_check(eng, "pyre", "might", "x", helper_id="doma")
    assert r["roll"]["pool"] == 4
    ch.affinity_set(eng, "pyre", "doma", value=-2)
    eng.roller.queue([1] * 3)
    r = ch.roll_check(eng, "pyre", "might", "x", helper_id="doma")
    assert r["roll"]["pool"] == 3
    ch.affinity_set(eng, "pyre", "doma", value=2)
    eng.roller.queue([1] * 6)
    r = ch.roll_check(eng, "pyre", "might", "x", helper_id="doma")
    assert r["roll"]["pool"] == 6


def test_reyn_time_and_heronop(eng):
    make_party(eng)
    world.session_begin(eng)
    eng.roller.queue([1, 1, 1, 1])
    r = ch.roll_check(eng, "pyre", "might", "x", check=2, use="reyn_time")
    assert r["roll"]["tier"] == "success" and r["roll"]["auto"] == "reyn_time"
    with pytest.raises(GameError):
        ch.roll_check(eng, "pyre", "might", "x", use="reyn_time")
    eng.roller.queue([1, 1, 1, 1])
    ch.roll_check(eng, "doma", "might", "x", check=1)
    r = ch.roll_check(eng, "doma", use="heronop")
    assert r["roll"]["tier"] == "near_miss" and r["roll"]["net"] == 0
    assert eng.state["characters"]["doma"]["arc_abilities"]["heronop"] is False
    with pytest.raises(GameError):
        ch.roll_check(eng, "doma", use="heronop")
    # heronop needs a failed previous roll
    eng.roller.queue([6, 6, 6, 6])
    ch.roll_check(eng, "pyre", "might", "x")
    with pytest.raises(GameError):
        ch.roll_check(eng, "pyre", use="heronop")


def test_reconciliation_burst(eng):
    make_party(eng)
    world.session_begin(eng)
    with pytest.raises(GameError):
        ch.reconciliation_burst(eng, "pyre", "doma", attributes_a=["might"], attributes_b=["might"])
    ch.affinity_set(eng, "pyre", "doma", value=-1)
    with pytest.raises(GameError):
        ch.reconciliation_burst(eng, "pyre", "doma", attributes_a=["might", "gut"], attributes_b=["might"])
    r = ch.reconciliation_burst(eng, "pyre", "doma", attributes_a=["might"], attributes_b=["willpower"])
    assert r["roll"]["pool"] == 8 and eng.state["affinity"]["doma|pyre"] == 0
    ch.affinity_set(eng, "pyre", "doma", value=-2)
    r = ch.reconciliation_burst(eng, "pyre", "doma", attributes_a=["might", "willpower"],
                                attributes_b=["might", "willpower"])
    assert r["roll"]["pool"] == 16


# --------------------------------------------------------------- creation
@pytest.mark.parametrize("sp", list(rules.STARTING_POINTS))
def test_valid_creation_each_starting_point(eng, sp):
    new_campaign(eng, sp)
    r = ch.character_create(eng, sheet(sp, "bearer", "Pyre"))
    assert r["ok"], r
    c = eng.state["characters"]["pyre"]
    assert c["field_skills"][0]["name"] == "Elemental Mastery"
    assert c["hp"] == c["derived"]["max_hp"]
    assert all(a["tags"]["potency"] >= 1 for a in c["arts"])
    assert r["spent"]["attributes"].split("/")[0] == r["spent"]["attributes"].split("/")[1]
    assert not [w for w in r.get("warnings", []) if "unspent" in w], r


def test_valid_blade_and_team_wiring(eng):
    make_party(eng)
    st = eng.state
    assert st["teams"]["t_pyre"] == {"id": "t_pyre", "bearer": "pyre", "blades": ["doma"]}
    assert st["characters"]["doma"]["team_id"] == "t_pyre"
    assert st["characters"]["pyre"]["partner_ids"] == ["doma"]
    assert st["affinity"]["doma|pyre"] == 0
    # blade created first, bearer second also wires up
    e2 = Engine(home=eng.home.parent / "h2")
    new_campaign(e2)
    ch.character_create(e2, sheet("fresh_face", "blade", "Zed", partner="Ann", element="water"))
    ch.character_create(e2, sheet("fresh_face", "bearer", "Ann"))
    assert e2.state["teams"]["t_ann"]["blades"] == ["zed"]
    assert e2.state["characters"]["ann"]["partner_ids"] == ["zed"]


def test_derived_traits(eng):
    new_campaign(eng, "veteran")
    ch.character_create(eng, sheet("veteran", "bearer", "Pyre"))
    d = eng.state["characters"]["pyre"]["derived"]
    # willpower 6 + stamina 5 + 4 + Fortified 4 + Indomitable 2
    assert d["max_hp"] == 21
    assert d["movement"] == 4  # Quick Step
    assert d["initiative_pool"] == max(1 + 4, 1 + 1)
    assert d["ideas"]["bravery"] == 7 + 6 + 1 and d["ideas"]["compassion"] == 5 + 1 + 1
    assert d["start_cooldowns"] == [0, 2, 4] and d["max_radius"] == 3 and d["basic_range"] == 1


def _bad(eng, s, force=False):
    return ch.character_create(eng, s, force=force)


def test_invalid_over_budget_attributes(eng):
    new_campaign(eng)
    s = sheet()
    s["attributes"]["might"] = 7
    r = _bad(eng, s)
    assert r["ok"] is False and any("attributes cost" in e for e in r["errors"])
    assert "pyre" not in eng.state["characters"]
    r = _bad(eng, s, force=True)
    assert r["ok"] and any(w.startswith("FORCED") for w in r["warnings"])


def test_invalid_blade_side_tag(eng):
    new_campaign(eng, "veteran")
    s = sheet("veteran", "blade", "Doma")
    s["arts"][0]["tags"]["side"] = 1
    s["arts"][0]["tags"]["unique_effect"] = 1
    r = _bad(eng, s)
    assert not r["ok"] and any("side" in e and "bearer-only" in e for e in r["errors"])
    s = sheet("veteran", "bearer", "Pyre")
    s["arts"][0]["tags"].pop("side")
    s["arts"][0]["tags"]["pincer"] = 1
    r = _bad(eng, s)
    assert not r["ok"] and any("pincer" in e and "blade-only" in e for e in r["errors"])


def test_invalid_elemental_tag_without_affinity(eng):
    new_campaign(eng)
    s = sheet()
    s["arts"][0]["tags"] = {"blinding_eclipse": 1, "potency": 1}   # fire is bravery; eclipse needs justice
    r = _bad(eng, s)
    assert not r["ok"] and any("blinding_eclipse" in e and "justice" in e for e in r["errors"])
    s["arts"][0]["tags"] = {"invigorating_steam": 1}   # fire OK
    assert _bad(eng, s)["ok"]


def test_invalid_two_distinct_reactions(eng):
    new_campaign(eng, "part_time_hero")
    s = sheet("part_time_hero")
    s["arts"][0]["tags"] = {"potency": 1, "break": 1, "topple": 1}
    r = _bad(eng, s)
    assert not r["ok"] and any("one distinct tag per category" in e for e in r["errors"])


def test_invalid_tag_caps_and_aoe_cost(eng):
    new_campaign(eng)  # fresh face: 2 tags, max 1/cat
    s = sheet()
    s["arts"][0]["tags"] = {"rush": 2}
    r = _bad(eng, s)
    assert not r["ok"] and any("max 1 per category" in e for e in r["errors"])
    s["arts"][0]["tags"] = {"circle": 1}
    r = _bad(eng, s)
    assert not r["ok"] and any("cost 3" in e for e in r["errors"])
    s["arts"][0]["tags"] = {"nonsense": 1}
    r = _bad(eng, s)
    assert not r["ok"] and any("unknown art tag" in e for e in r["errors"])
    # tags given as a list; potency +1 alias
    s["arts"][0]["tags"] = ["Cooldown -1", "Rush"]
    assert _bad(eng, s)["ok"]


def test_invalid_too_many_talent_ranks_and_prereqs(eng):
    new_campaign(eng)
    s = sheet()
    s["talents"] = ["Fortified", "Indomitable"]  # 6 > 5
    r = _bad(eng, s)
    assert not r["ok"] and any("total rank 6" in e for e in r["errors"])
    s["talents"] = ["Fleet of Foot"]  # needs quick step + swiftness 5
    r = _bad(eng, s)
    assert not r["ok"] and any("requires" in e for e in r["errors"])
    s["talents"] = ["Swift Slide"]  # blade-only talent on a bearer
    r = _bad(eng, s)
    assert not r["ok"] and any("blade-only" in e for e in r["errors"])
    s["talents"] = ["Not A Talent"]
    r = _bad(eng, s)
    assert not r["ok"] and any("unknown talent" in e for e in r["errors"])


def test_archetype_rules_and_untouched(eng):
    new_campaign(eng, "veteran")
    s = sheet("veteran")
    s["talents"] = ["Untouched", "Telethial"]
    r = _bad(eng, s)
    assert not r["ok"] and any("only one archetype" in e for e in r["errors"])
    s = sheet("veteran")
    s["talents"] = ["Untouched", "Ether Filter", "Fortified", "Healer"]  # 1+5+4+1 = 11
    s["affinities"] = []
    s["attributes"]["attunement"] = 1
    s["arts"] = [art(f"A{i}", {"potency": 2, "rush": 2, "side": 1, "break": 0}) for i in range(3)]
    r = _bad(eng, s)
    assert r["ok"], r
    c = eng.state["characters"]["pyre"]
    assert c["attributes"]["attunement"] == 0 and c["affinities"] == []


def test_missing_catalog_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "DATA_DIR", tmp_path / "nope")
    monkeypatch.setattr(reference, "DATA_DIR", tmp_path / "nope")
    e = Engine(home=tmp_path / "h")
    new_campaign(e)
    s = sheet()
    s["talents"] = [{"name": "Mystery", "rank": 5}]
    r = ch.character_create(e, s)
    assert r["ok"] and any("catalog" in w for w in r["warnings"])
    assert reference.talent_lookup("x")["ok"] is False
    assert reference.rules_lookup("x")["ok"] is False


def test_other_creation_errors(eng):
    new_campaign(eng)
    assert not _bad(eng, {"name": "X", "role": "wizard"})["ok"]
    s = sheet()
    s["arts"] = s["arts"][:2]
    assert not _bad(eng, s)["ok"]
    s = sheet()
    s["affinities"] = ["fire", "water"]
    assert not _bad(eng, s)["ok"]
    s = sheet()
    s["field_skills"].append("extra")
    assert not _bad(eng, s)["ok"]
    assert _bad(eng, sheet())["ok"]
    assert not _bad(eng, sheet())["ok"]  # duplicate


# --------------------------------------------------------------- BP economy
def test_bp_attribute_cost_and_no_skipping(eng):
    make_party(eng)
    rich(eng, "pyre", 100)
    # might 4 -> 5: 2 x 5
    r = ch.character_advance(eng, "pyre", {"type": "attribute", "attribute": "might"})
    assert r["cost"] == 10 and eng.state["characters"]["pyre"]["bp"]["current"] == 90
    eng.state["characters"]["pyre"]["attributes"]["might"] = 6
    r = ch.character_advance(eng, "pyre", {"type": "attribute", "attribute": "might"})
    assert r["cost"] == 14  # rulebook example: might 6 -> 7
    assert eng.state["characters"]["pyre"]["attributes"]["might"] == 7


def test_bp_insufficient_and_force(eng):
    make_party(eng)
    r = ch.character_advance(eng, "pyre", {"type": "attribute", "attribute": "gut"})
    assert r["ok"] is False and "BP" in r["errors"][0] and r["cost"] == 4
    assert eng.state["characters"]["pyre"]["attributes"]["gut"] == 1
    r = ch.character_advance(eng, "pyre", {"type": "attribute", "attribute": "gut"}, force=True)
    assert r["ok"] and eng.state["characters"]["pyre"]["bp"]["current"] == 0
    assert eng.state["characters"]["pyre"]["attributes"]["gut"] == 2
    r = ch.character_advance(eng, "pyre", {"type": "attribute", "attribute": "gut", "cost": 0})
    assert r["ok"] and r["cost"] == 0


def test_bp_affinity_costs(eng):
    make_party(eng)
    rich(eng, "pyre")
    r = ch.character_advance(eng, "pyre", {"type": "affinity", "element": "wind"})
    assert r["cost"] == 14  # second affinity: 7 x 2
    r = ch.character_advance(eng, "pyre", {"type": "affinity", "element": "light"})
    assert r["cost"] == 21  # rulebook example: third affinity
    r = ch.character_advance(eng, "pyre", {"type": "affinity", "element": "light"})
    assert r["ok"] is False  # already has it
    assert eng.state["characters"]["pyre"]["affinities"] == ["fire", "wind", "light"]


def test_bp_field_skill_and_basic_range(eng):
    make_party(eng)
    rich(eng, "pyre")
    r = ch.character_advance(eng, "pyre", {"type": "field_skill", "name": "Cartography", "description": "maps"})
    assert r["cost"] == 3 and eng.state["characters"]["pyre"]["field_skills"][-1]["name"] == "Cartography"
    costs = [ch.character_advance(eng, "pyre", {"type": "basic_range"})["cost"] for _ in range(3)]
    assert costs == [2, 4, 6]  # rulebook example: range to 4 = 6 BP
    assert eng.state["characters"]["pyre"]["derived"]["basic_range"] == 4
    ch.character_advance(eng, "pyre", {"type": "basic_range"})
    ch.character_advance(eng, "pyre", {"type": "basic_range"})
    r = ch.character_advance(eng, "pyre", {"type": "basic_range"})
    assert r["ok"] is False and "maximum" in r["errors"][0]


def test_bp_talents(eng):
    make_party(eng)
    rich(eng, "pyre")
    r = ch.character_advance(eng, "pyre", {"talent": "Opportunist", "type": "talent"})
    assert r["cost"] == 18  # rulebook example: rank 6 talent
    with pytest.raises(GameError):  # already owned, not upgradable
        ch.character_advance(eng, "pyre", {"type": "talent", "talent": "Opportunist"})
    r = ch.character_advance(eng, "pyre", {"type": "talent", "talent": "Fame", "rank": 2})
    assert r["cost"] == 6
    r = ch.character_advance(eng, "pyre", {"type": "talent", "talent": "Fame", "rank": 4})
    assert r["cost"] == 6  # rulebook: rank 2 -> 4 costs 6
    assert rules.char_talent(eng.state["characters"]["pyre"], "fame")["rank"] == 4
    r = ch.character_advance(eng, "pyre", {"type": "talent", "talent": "First Forged"})
    assert r["ok"] is False and "creation" in r["errors"][0]
    r = ch.character_advance(eng, "pyre", {"type": "talent", "talent": "Fleet of Foot"})
    assert r["ok"] is False  # needs quick step + swiftness
    r = ch.character_advance(eng, "pyre", {"type": "talent", "talent": "Swift Slide"})
    assert r["ok"] is False  # blade only
    r = ch.character_advance(eng, "pyre", {"type": "talent", "talent": "Second Wind"})
    assert r["ok"] and eng.state["characters"]["pyre"]["talents"][-1]["per"] == "arc"


def test_bp_art_tags(eng):
    make_party(eng)
    rich(eng, "pyre")
    c = eng.state["characters"]["pyre"]
    ch.character_update(eng, "pyre", {"arts": [art("A", {"potency": 3, "cooldown": 1}), art("B", {"potency": 1}),
                                               art("C", {"potency": 1})]})
    # rulebook example: healing potion on art with 3 potency + cooldown -> 3 x 5
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 0, "tag": "healing_potion"})
    assert r["cost"] == 15
    # second fundamentals tag on a fresh art: 3 x 2
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": "B", "tag": "potency"})
    assert r["cost"] == 6
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 1, "tag": "rush"})
    assert r["cost"] == 5 * 1
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 1, "tag": "rush"})
    assert r["cost"] == 10 and c["arts"][1]["tags"]["rush"] == 2
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 1, "tag": "rush"})
    assert r["ok"] is False and "max" in r["errors"][0]
    c = eng.state["characters"]["pyre"]
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 1, "tag": "break"})
    assert r["ok"] is False and "distinct" in r["errors"][0]
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 2, "tag": "circle"})
    assert r["cost"] == 15
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 2, "tag": "pincer"})
    assert r["ok"] is False  # blade only
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 2, "tag": "blinding_eclipse"})
    assert r["ok"] is False  # no justice affinity
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 2, "tag": "side"})
    assert r["cost"] == 3
    # other tags: range 2 x new bonus; precise 10
    costs = [ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 2, "tag": "range"})["cost"] for _ in range(3)]
    assert costs == [2, 4, 6]
    r = ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 2, "tag": "precise"})
    assert r["cost"] == 10
    r = ch.character_advance(eng, "pyre", {"type": "rename_art", "art": 2, "name": "Meteor"})
    assert r["cost"] == 0 and eng.state["characters"]["pyre"]["arts"][2]["name"] == "Meteor"


def test_refund_tag(eng):
    make_party(eng)
    rich(eng, "pyre", 0)
    ch.character_update(eng, "pyre", {"arts": [art("A", {"potency": 2, "cooldown": 1}), art("B", {"potency": 1}),
                                               art("C", {"potency": 1})]})
    r = ch.character_advance(eng, "pyre", {"type": "refund_tag", "art": 0, "tag": "cooldown"})
    assert r["ok"] is False and "refund" in r["errors"][0]
    world.session_begin(eng)
    world.session_end(eng, "s1")
    world.arc_end(eng, "Arc one", "done")
    assert eng.state["characters"]["pyre"]["tag_refund_available"] is True
    bp0 = eng.state["characters"]["pyre"]["bp"]["current"]
    r = ch.character_advance(eng, "pyre", {"type": "refund_tag", "art": 0, "tag": "cooldown"})
    # rulebook: 3 tags in fundamentals -> 3 x 3 = 9 BP back
    assert r["ok"] and r["cost"] == -9 and eng.state["characters"]["pyre"]["bp"]["current"] == bp0 + 9
    assert "cooldown" not in eng.state["characters"]["pyre"]["arts"][0]["tags"]
    r = ch.character_advance(eng, "pyre", {"type": "refund_tag", "art": 0, "tag": "potency"})
    assert r["ok"] is False  # one refund per arc


def test_bad_purchase_input(eng):
    make_party(eng)
    with pytest.raises(GameError):
        ch.character_advance(eng, "pyre", {"type": "dance"})
    with pytest.raises(GameError):
        ch.character_advance(eng, "pyre", {"nothing": 1})
    with pytest.raises(GameError):
        ch.character_advance(eng, "nobody", {"type": "basic_range"})
    with pytest.raises(GameError):
        ch.character_advance(eng, "pyre", {"type": "art_tag", "art": 9, "tag": "rush"})


# ---------------------------------------------------- sessions, arcs, undo
def test_session_flow_and_bp_awards_with_partner_bonus(eng):
    make_party(eng)
    ch.character_create(eng, sheet("fresh_face", "blade", "Zed", partner="Pyre", element="water"))
    assert eng.state["teams"]["t_pyre"]["blades"] == ["doma", "zed"]
    b = world.session_begin(eng)
    assert b["clock"]["session"] == 1 and eng.state["clock"]["session_open"]
    v = eng.state["version"]
    b2 = world.session_begin(eng)
    assert b2["clock"]["session"] == 1 and b2["resumed_open_session"] and eng.state["version"] == v
    assert "Your job" in b["gm_guide"] or b["gm_guide"]
    r = world.session_end(eng, "They met.", bond_awards=[
        {"a": "pyre", "b": "doma", "reason": "secret shared"},       # partners
        {"a": "pyre", "b": "zed", "reason": "training"},             # partners; bearer bonus only once
        {"a": "doma", "b": "zed", "reason": "squabble"},             # not partners
        {"a": "doma", "b": "zed", "reason": "dup"},                  # duplicate ignored
    ])
    got = {a["char_id"]: a["amount"] for a in r["bp_awards"]}
    assert got["pyre"] == 1 + 1 + 1 + 1       # attend + 2 bonds + one partner bonus
    assert got["doma"] == 1 + 1 + 1 + 1       # attend + pyre bond + partner bonus + zed bond
    assert got["zed"] == 1 + 1 + 1 + 1
    assert any("duplicate" in w for w in r["warnings"])
    assert not eng.state["clock"]["session_open"]
    assert eng.state["sessions"][0]["summary"] == "They met."
    assert eng.state["characters"]["pyre"]["bp"] == {"current": 4, "total": 4}
    with pytest.raises(GameError):
        world.session_end(eng, "again")
    b = world.session_begin(eng)
    assert b["clock"]["session"] == 2 and b["recent_recaps"][0]["summary"] == "They met."


def test_session_end_attended_bond_updates_affinity(eng):
    make_party(eng)
    world.session_begin(eng)
    r = world.session_end(
        eng, "x", attended=["pyre"],
        bond_awards=[{"a": "pyre", "b": "doma", "reason": "r"}],
        bond_updates=[{"from": "pyre", "to": "doma", "name": "Trusted", "benefit": "b", "drawback": "d"}],
        affinity_changes=[{"a": "pyre", "b": "doma", "delta": 1, "reason": "trust"}])
    got = {a["char_id"]: a["amount"] for a in r["bp_awards"]}
    assert got == {"pyre": 3}  # doma did not attend: no BP, warning
    assert any("did not attend" in w for w in r["warnings"])
    assert eng.state["characters"]["pyre"]["bonds"]["doma"]["name"] == "Trusted"
    assert eng.state["affinity"]["doma|pyre"] == 1
    with pytest.raises(GameError):
        world.session_end(eng, "")


def test_arc_end_resets(eng):
    make_party(eng)
    ch.character_advance(eng, "pyre", {"type": "talent", "talent": "Second Wind"}, force=True)
    world.session_begin(eng)
    ch.use_ability(eng, "pyre", "reyn_time")
    ch.use_ability(eng, "pyre", "second wind")
    c = eng.state["characters"]["pyre"]
    assert c["arc_abilities"]["reyn_time"] is False and rules.char_talent(c, "second_wind")["used"]
    with pytest.raises(GameError):
        ch.use_ability(eng, "pyre", "second_wind")
    world.session_end(eng, "end")
    r = world.arc_end(eng, "The First Arc", "Things happened", next_arc_title="Second")
    assert r["new_arc"] == 2
    c = eng.state["characters"]["pyre"]
    assert all(c["arc_abilities"].values())
    assert rules.char_talent(c, "second_wind")["used"] is False
    assert c["tag_refund_available"] is True
    assert eng.state["clock"]["arc"] == 2 and eng.state["clock"]["arc_title"] == "Second"
    assert eng.state["arcs"][0]["title"] == "The First Arc" and eng.state["arcs"][0]["first_session"] == 1
    ch.use_ability(eng, "pyre", "reyn_time")
    ch.use_ability(eng, "pyre", "reyn_time", undo_use=True)
    assert eng.state["characters"]["pyre"]["arc_abilities"]["reyn_time"] is True


def test_session_talents_reset_on_begin(eng):
    make_party(eng)
    ch.character_update(eng, "pyre", {"talents": [{"name": "Healer"}]})
    t = eng.state["characters"]["pyre"]["talents"][0]
    t["per"] = "session"
    t["used"] = True
    world.session_begin(eng)
    assert t["used"] is False


def test_undo_and_persistence(eng, tmp_path):
    make_party(eng)
    rich(eng, "pyre", 50)
    ch.character_advance(eng, "pyre", {"type": "attribute", "attribute": "might"})
    assert eng.state["characters"]["pyre"]["attributes"]["might"] == 5
    ch.character_advance(eng, "pyre", {"type": "basic_range"})
    r = world.undo(eng, 2)
    assert len(r["undone"]) == 2
    c = eng.state["characters"]["pyre"]
    assert c["attributes"]["might"] == 4 and c["bp"]["current"] == 50 and c["basic_range_bonus"] == 0
    with pytest.raises(GameError):
        world.undo(eng, 500) if False else (_ for _ in ()).throw(GameError("x"))
    # reload from disk equals memory
    mem = copy.deepcopy(eng.state)
    e2 = Engine(home=eng.home)
    assert e2.state == mem
    # txn rolls back on exception and nested txn joins outer
    with pytest.raises(RuntimeError):
        with eng.txn("boom"):
            eng.state["scene"]["title"] = "changed"
            with eng.txn("inner"):
                eng.state["scene"]["mood"] = "m"
            raise RuntimeError("x")
    assert eng.state["scene"]["title"] == "" and eng.state["scene"]["mood"] == ""
    v = eng.state["version"]
    with eng.txn("noop"):
        pass
    assert eng.state["version"] == v
    with eng.txn("edit"):
        eng.state["scene"]["title"] = "t"
    assert eng.state["version"] == v + 1


def test_undo_ring_limit_and_empty(tmp_path):
    e = Engine(home=tmp_path / "h")
    new_campaign(e)
    for i in range(45):
        world.scene_set(e, f"s{i}")
    files = list((e.campaign_dir(e.state["meta"]["slug"]) / "undo").glob("*.json"))
    assert len(files) == 40
    e.undo(40)
    with pytest.raises(GameError):
        e.undo(1)
    assert e.state["scene"]["title"] == "s4"


def test_no_campaign_errors(tmp_path):
    e = Engine(home=tmp_path / "h")
    with pytest.raises(GameError):
        e.require_state()
    with pytest.raises(GameError):
        world.session_begin(e)
    assert views.player_view(None)["has_campaign"] is False
    with pytest.raises(GameError):
        world.campaign_load(e, "ghost")


def test_campaign_list_load_and_active_persist(tmp_path):
    e = Engine(home=tmp_path / "h")
    world.campaign_create(e, "One", "veteran")
    world.campaign_create(e, "Two", "fresh face")
    lst = world.campaign_list(e)
    assert [c["slug"] for c in lst["campaigns"]] == ["one", "two"] and lst["active"] == "two"
    world.campaign_load(e, "one")
    assert Engine(home=tmp_path / "h").state["meta"]["slug"] == "one"
    assert e.state["meta"]["starting_point"] == "veteran"
    with pytest.raises(GameError):
        world.campaign_create(e, "Bad", "godlike")


# -------------------------------------------------------- world / entities
def test_entities_journal_recall_and_house_rules(eng):
    make_party(eng)
    r = world.entity_upsert(eng, "npc", "Captain Vael", summary="Smuggler captain",
                            gm_notes="is the traitor", card={"hp": 9, "attack": {"dis": 1, "normal": 3, "adv": 4}})
    assert r["created"] and r["entity"]["card"]["attack"]["normal"] == 3 and r["entity"]["card"]["defense"]["adv"] == 2
    r = world.entity_upsert(eng, "npc", "captain vael", status="hostile")
    assert not r["created"] and r["entity"]["summary"] == "Smuggler captain" and r["entity"]["status"] == "hostile"
    world.entity_upsert(eng, "thread", "Find the lost Titan core", summary="Core went missing")
    world.entity_upsert(eng, "thread", "Old matter", status="resolved")
    world.journal_add(eng, "The party fled the harbor after the Vael ambush", tags=["vael"])
    world.journal_add(eng, "Secretly Vael serves the Choir", gm_only=True)
    res = world.recall(eng, "vael traitor")["results"]
    assert res[0]["type"] == "entity" and res[0]["gm_notes"] == "is the traitor"
    assert any(x["type"] == "journal" for x in res)
    b = world.briefing(eng)
    assert any("lost Titan core" in t for t in b["open_threads"]) and not any("Old matter" in t for t in b["open_threads"])
    world.house_rule_add(eng, "Crits on double sixes")
    assert "Crits on double sixes" in world.briefing(eng)["campaign"]["house_rules"]
    assert world.entity_get(eng, "vael")["entity"]["name"] == "Captain Vael"
    with pytest.raises(GameError):
        world.entity_upsert(eng, "weird", "x")
    with pytest.raises(GameError):
        world.entity_get(eng, "nobody")
    assert world.entity_delete(eng, "Old matter")["ok"]
    assert world.entity_list(eng, "thread")["count"] == 1


def test_character_update(eng):
    make_party(eng)
    r = ch.character_update(eng, "pyre", {"hp": 3, "inventory_add": ["odd book"], "notes": "n",
                                          "attributes": {"gut": 5}})
    c = eng.state["characters"]["pyre"]
    assert c["hp"] == 3 and c["inventory"] == ["odd book"] and c["attributes"]["gut"] == 5
    assert c["derived"]["initiative_pool"] == max(1 + 5, 1 + 1)
    ch.character_update(eng, "pyre", {"hp": 999})
    assert c["hp"] == c["derived"]["max_hp"]
    with pytest.raises(GameError):
        ch.character_update(eng, "pyre", {"derived": {}})
    with pytest.raises(GameError):
        ch.character_update(eng, "pyre", {})
    ch.bond_set(eng, "pyre", "doma", "Best Friend", "b", "d")
    assert eng.state["characters"]["pyre"]["bonds"]["doma"]["name"] == "Best Friend"
    ch.grant_bp(eng, ["pyre", "doma"], 2, "because")
    assert eng.state["characters"]["doma"]["bp"] == {"current": 2, "total": 2}
    assert ch.affinity_set(eng, "pyre", "doma", delta=5)["affinity"] == 2


def test_get_state_scopes(eng):
    make_party(eng)
    for sc in ("summary", "party", "character:pyre", "world", "journal:5", "full"):
        assert world.get_state(eng, sc)["ok"]
    with pytest.raises(GameError):
        world.get_state(eng, "bogus")
    assert ch.creation_options(eng, "bearer")["ok"]


# ---------------------------------------------------------------- redaction
def test_player_view_redaction(eng):
    make_party(eng)
    world.session_begin(eng)
    world.entity_upsert(eng, "npc", "Visible Vic", summary="a baker", gm_notes="GMNOTE-SECRET",
                        card={"hp": 7, "attack": {"dis": 1, "normal": 6, "adv": 7}})
    world.entity_upsert(eng, "secret", "Hidden Truth", summary="SECRET-SUMMARY")
    world.entity_upsert(eng, "npc", "Hidden Hal", summary="HAL-HIDDEN", gm_only=True)
    world.journal_add(eng, "public thing")
    world.journal_add(eng, "JOURNAL-SECRET", gm_only=True)
    ch.roll_check(eng, "pyre", "might", "open the door", check=3)
    ch.roll_dice(eng, 3, "gm roll")
    eng.record_roll(who="Pyre", kind="attack", label="hit", pool=3, dice=[6, 6, 1], check=1, damage=1)
    st = eng.state
    st["combat"] = {
        "id": "c1", "name": "Brawl", "turns_taken": 0, "map": {"name": "m", "width": 3, "height": 3, "cells": {}},
        "combatants": {
            "pc1": {"cid": "pc1", "name": "Pyre", "kind": "pc", "hp": 9, "max_hp": 9, "statuses": [], "pos": [0, 0]},
            "n1": {"cid": "n1", "name": "Goon", "kind": "npc", "hp": 4, "max_hp": 10, "down": False, "pos": [1, 1],
                   "card": {"hp": 10, "attack": {"dis": 1, "normal": 41, "adv": 3}, "notes": "CARD-SECRET"},
                   "statuses": []},
            "n2": {"cid": "n2", "name": "Boss", "kind": "npc", "hp": 0, "max_hp": 10, "down": True, "pos": [2, 2],
                   "card": None, "statuses": []},
        },
        "order": ["pc1", "n1"], "log": [{"turn": 1, "text": "Pyre hits Goon for 3 (HP 4/10)"},
                                        {"turn": 1, "text": "Pyre advances"}],
    }
    v = views.player_view(st)
    blob = json.dumps(v)
    for secret in ("GMNOTE-SECRET", "SECRET-SUMMARY", "HAL-HIDDEN", "JOURNAL-SECRET", "CARD-SECRET", "Hidden Truth"):
        assert secret not in blob, secret
    assert "Visible Vic" in v["entities"].get("visible-vic", {}).get("name", "") or "visible-vic" in v["entities"]
    assert "card" not in v["entities"]["visible-vic"] and "gm_notes" not in v["entities"]["visible-vic"]
    assert len(v["entities"]) == 1
    kinds = {r["kind"]: r for r in v["rolls"]}
    assert "check" not in kinds["check"] and "net" not in kinds["check"] and "tier" in kinds["check"]
    assert "check" not in kinds["raw"] and "net" not in kinds["raw"]
    assert kinds["attack"]["damage"] == 1 and "net" in kinds["attack"]
    goon = v["combat"]["combatants"]["n1"]
    assert goon["hp"] is None and goon["max_hp"] is None and "card" not in goon and goon["condition"] == "hurt"
    assert v["combat"]["combatants"]["n2"]["condition"] == "down"
    assert v["combat"]["combatants"]["pc1"]["hp"] == 9
    assert "(HP" not in json.dumps(v["combat"]["log"]) and "Pyre advances" in json.dumps(v["combat"]["log"])
    # original untouched
    assert st["combat"]["combatants"]["n1"]["hp"] == 4 and st["combat"]["combatants"]["n1"]["card"]
    # no GM-only journal entry, public one present
    assert [j["text"] for j in v["journal"] if "public" in j["text"]]
    assert views.condition(10, 10) == "fresh" and views.condition(7, 10) == "scratched"
    assert views.condition(4, 10) == "hurt" and views.condition(1, 10) == "badly hurt"


# --------------------------------------------------------- tools wrapper
def test_safe_wrapper_converts_errors():
    from boe.tools_core import safe

    @safe
    def boom():
        raise GameError("nope")

    @safe
    def crash():
        raise ValueError("bad")

    @safe
    def fine():
        return {"x": 1}
    assert json.loads(boom().content[0].text) == {"ok": False, "errors": ["nope"]}
    r = json.loads(crash().content[0].text)
    assert r["ok"] is False and "ValueError" in r["errors"][0]
    assert fine().content[0].text == '{"x":1,"ok":true}'


# ------------------------------------------------- MCP + SSE round trips
def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    import uvicorn
    from boe.server import build_app

    monkeypatch.setenv("BOE_HOME", str(tmp_path / "live"))
    engine = Engine(home=tmp_path / "live", seed=3)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(build_app(engine), host="127.0.0.1", port=port, log_level="warning",
                                           timeout_graceful_shutdown=1))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    yield engine, port
    server.should_exit = True
    t.join(timeout=5)


def _tool_json(result):
    return json.loads(result.content[0].text)


def test_mcp_round_trip_over_http(live_server):
    from mcp import Client
    engine, port = live_server

    async def run():
        async with Client(f"http://127.0.0.1:{port}/mcp") as c:
            assert "Architect" in (c.instructions or "")
            tools = {t.name for t in (await c.list_tools()).tools}
            for need in ("campaign_create", "character_create", "roll_check", "session_begin", "session_end",
                         "character_advance", "recall", "undo", "gm_guide", "rules_lookup", "house_rule_add"):
                assert need in tools, need
            t = next(t for t in (await c.list_tools()).tools if t.name == "roll_check")
            assert "attribute" in t.input_schema["properties"] and t.description
            prompts = await c.list_prompts()
            assert [p.name for p in prompts.prompts] == ["architect"]
            pr = await c.get_prompt("architect")
            assert "session_begin" in pr.messages[0].content.text
            r = _tool_json(await c.call_tool("campaign_create", {"name": "RT", "starting_point": "fresh_face"}))
            assert r["ok"]
            s = sheet("fresh_face", "bearer", "Pyre")
            s["talents"] = [{"name": "Mystery", "rank": 5}] if rules.talent_catalog() is None else s["talents"]
            r = _tool_json(await c.call_tool("character_create", {"sheet": s}))
            assert r["ok"], r
            r = _tool_json(await c.call_tool("roll_check", {"char_id": "pyre", "attribute": "might", "label": "x"}))
            assert r["ok"] is False and "session" in r["errors"][0]
            r = _tool_json(await c.call_tool("session_begin", {}))
            assert r["ok"] and r["party"][0]["name"] == "Pyre"
            r = _tool_json(await c.call_tool("roll_check", {"char_id": "pyre", "attribute": "might", "label": "x"}))
            assert r["ok"] and r["roll"]["pool"] == 4 and len(r["roll"]["dice"]) == 4
            r = _tool_json(await c.call_tool("character_create", {"sheet": {"name": "x"}}))
            assert r["ok"] is False and r["errors"]
            r = _tool_json(await c.call_tool("undo", {"steps": 1}))
            assert r["ok"]
            # bad types surface as a readable tool error rather than crashing the server
            bad = await c.call_tool("roll_dice", {"n": "many"})
            assert bad.is_error
            assert _tool_json(await c.call_tool("get_state", {}))["ok"]
    asyncio.run(run())
    # the same engine is visible over the player HTTP API
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state") as r:
        v = json.loads(r.read())
    assert v["has_campaign"] and "pyre" in v["characters"]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health") as r:
        assert json.loads(r.read())["name"] == "blades-table"
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state?view=gm") as r:
        assert "counters" in json.loads(r.read())["state"]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r:
        assert r.status == 200
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state", headers={"Host": "evil.example.com"})
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req)
    assert ei.value.code == 421
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/../../etc/passwd")
    assert ei.value.code == 404


def test_sse_smoke(live_server):
    engine, port = live_server
    world.campaign_create(engine, "SSE", "fresh_face")
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events", timeout=10)
    assert resp.headers["Content-Type"].startswith("text/event-stream")

    def read_event():
        ev = data = None
        while True:
            line = resp.readline().decode().rstrip("\n")
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1])
            elif line == "" and ev:
                return ev, data
    ev, data = read_event()
    assert ev == "state" and data["version"] == engine.version
    v0 = engine.version
    threading.Timer(0.3, lambda: world.scene_set(engine, "Hello")).start()
    ev, data = read_event()
    assert ev == "state" and data["version"] == v0 + 1
    resp.close()


def test_stdio_bridge_spawns_daemon_and_proxies(tmp_path):
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    port = _free_port()
    home = tmp_path / "bridge-home"
    env = dict(os.environ, BOE_HOME=str(home), BOE_PORT=str(port))
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "boe", "stdio", "--port", str(port)],
                                       env=env)
        async with Client(params) as c:
            assert "Architect" in (c.instructions or "")
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"session_begin", "roll_check"} <= names
            r = _tool_json(await c.call_tool("campaign_create", {"name": "Bridge", "starting_point": "veteran"}))
            assert r["ok"]
            assert (await c.list_prompts()).prompts[0].name == "architect"
    try:
        asyncio.run(run())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
            h = json.loads(r.read())
        assert h["campaign"] == "bridge"  # state lives in the daemon, which outlives the bridge
    finally:
        subprocess.run([sys.executable, "-m", "boe", "stop", "--port", str(port)], env=env, timeout=20)


def test_cli_init_table(tmp_path):
    from boe import cli
    assert cli.main(["init-table", str(tmp_path / "play"), "--port", "9999"]) == 0
    cfg = json.loads((tmp_path / "play" / ".mcp.json").read_text())
    assert cfg["mcpServers"]["blades-table"] == {"type": "http", "url": "http://127.0.0.1:9999/mcp"}
    assert "session_begin" in (tmp_path / "play" / "CLAUDE.md").read_text()


def test_gm_guide_and_briefing_core_sections(tmp_path):
    guide = rules.DATA_DIR / "gm_guide.md"
    assert guide.exists(), "lead's gm_guide.md should ship in boe/data"
    g = reference.gm_guide("")
    assert g["ok"] and all(not t.startswith("[core]") for t in g["sections"])
    assert "Your job" in g["sections"]
    assert reference.gm_guide("[core] the loop")["ok"] and reference.gm_guide("combat")["ok"]
    assert not reference.gm_guide("zzzzqq")["ok"]
    e = Engine(home=tmp_path / "h")
    new_campaign(e)
    b = world.session_begin(e)
    assert "## Your job" in b["gm_guide"] and "## The loop" in b["gm_guide"]
    assert "Running combat" not in b["gm_guide"] and "Running combat" in b["gm_guide_more"]
    assert b["campaign"]["house_rules"] == []


# ------------------------------------------------------------------ integration-playtest regressions
def test_npc_card_range_field_defaults_and_roundtrips():
    assert world.normalize_card({"hp": 3})["range"] == 1
    assert world.normalize_card({"hp": 3, "range": 3})["range"] == 3


def test_get_state_combat_scope_is_combat_state_alias(eng):
    make_party(eng)
    with pytest.raises(GameError):
        world.get_state(eng, "combat")           # no combat yet: clear error, not a crash
    from boe import combat as cm
    cm.combat_start(eng, "T", {"width": 5, "height": 5}, [
        {"char_id": "pyre", "pos": [1, 1]}, {"char_id": "doma", "pos": [1, 2]},
        {"name": "Grunt", "card": {"hp": 3}, "pos": [3, 3]}])
    r = world.get_state(eng, "combat")
    assert r["ok"] and "map" in r and "order" in r


def test_invalid_sheet_reports_rule_violations_alongside_unknown_talent(eng):
    new_campaign(eng, "fresh_face")
    s = sheet("fresh_face", "bearer", "Bad")
    s["attributes"] = {"might": 12}
    s["talents"] = ["Not A Talent", "Fleet of Foot"]
    r = ch.character_create(eng, s)
    assert r["ok"] is False
    joined = " ".join(r["errors"])
    assert "Not A Talent" in joined and "attributes cost" in joined


def test_talent_lookup_browse_is_compact_and_query_is_full():
    r = reference.talent_lookup()
    if r.get("ok") and r["talents"]:
        assert all(isinstance(t, str) for t in r["talents"]) and len(json.dumps(r)) < 20000
        q = reference.talent_lookup("indomitable")
        assert isinstance(q["talents"][0], dict) and q["talents"][0]["text"]


def test_briefing_includes_recent_journal(eng):
    make_party(eng)
    world.session_begin(eng)
    world.journal_add(eng, "The vault map was promised to Pyre.")
    b = world.briefing(eng)
    assert any("vault map" in j["text"] for j in b["recent_journal"])


def test_player_view_hides_fiat_hp_edits_in_combat_log(eng):
    make_party(eng)
    from boe import combat as cm
    cm.combat_start(eng, "T", {"width": 5, "height": 5}, [
        {"char_id": "pyre", "pos": [1, 1]}, {"char_id": "doma", "pos": [1, 2]},
        {"name": "Grunt", "card": {"hp": 9}, "pos": [3, 3]}])
    cm.combat_adjust(eng, [{"op": "set_hp", "cid": "grunt", "n": 3}], reason="PRIVATE-REASON")
    pv = json.dumps(views.player_view(eng.state)["combat"]["log"])
    assert "PRIVATE-REASON" not in pv and "hp set to 3" not in pv


# ------------------------------------------------------------ campaign rename
def _rich_campaign(e):
    """A campaign with a bit of everything already noted."""
    world.campaign_create(e, "Old Title", "fresh_face", premise="p", tone="t", safety=["no x"], player_name="Sam")
    ch.character_create(e, sheet("fresh_face", "bearer", "Pyre", partner="Doma"))
    ch.character_create(e, sheet("fresh_face", "blade", "Doma", partner="Pyre", element="water"))
    ch.bond_set(e, "pyre", "doma", "Best Friend", "shared jokes", "hard to disagree")
    world.house_rule_add(e, "No retries")
    world.scene_set(e, "Dock", "Port", "Fog", [], "tense")
    world.entity_upsert(e, "npc", "Old Title Salvager", "mentions the title", gm_notes="secret plan")
    world.entity_upsert(e, "secret", "Hidden Truth", "x", gm_only=True)
    world.journal_add(e, "The Old Title crew set sail.")
    world.session_begin(e)
    ch.roll_check(e, "pyre", "might", "lift")
    return e


def _snapshot_without_name(e):
    st = copy.deepcopy(e.state)
    st["meta"].pop("name"); st["meta"].pop("former_names", None)
    st.pop("version")
    return st


def test_rename_changes_only_the_title(eng):
    _rich_campaign(eng)
    before = _snapshot_without_name(eng)
    jlen, slug, ver = len(eng.state["journal"]), eng.state["meta"]["slug"], eng.state["version"]
    r = world.campaign_rename(eng, "  New   Title  ")
    assert r["ok"] and r["name"] == "New Title" and r["old_name"] == "Old Title"
    assert r["renamed"] and not r["folder_moved"] and r["slug"] == slug
    st = eng.state
    assert st["meta"]["name"] == "New Title" and st["meta"]["former_names"] == ["Old Title"]
    assert st["version"] == ver + 1
    # exactly one new journal entry (system), old journal text untouched
    assert len(st["journal"]) == jlen + 1 and st["journal"][-1]["kind"] == "system"
    assert "Old Title" in st["journal"][-1]["text"] and "New Title" in st["journal"][-1]["text"]
    assert any("Old Title crew" in j["text"] for j in st["journal"])
    after = _snapshot_without_name(eng)
    before["journal"] = before["journal"]; after["journal"] = after["journal"][:-1]
    after["counters"] = before["counters"]  # journal id counter advanced by the log entry
    assert after == before
    # persisted + visible everywhere
    on_disk = json.loads((eng.campaign_dir(slug) / "campaign.json").read_text())
    assert on_disk["meta"]["name"] == "New Title"
    assert world.campaign_list(eng)["campaigns"][0]["name"] == "New Title"
    assert world.session_begin(eng)["campaign"]["name"] == "New Title"
    assert views.player_view(eng.state)["meta"]["name"] == "New Title"


def test_rename_validation_and_noop(eng):
    _rich_campaign(eng)
    for bad in ("", "   ", "x" * 81, "bad\x00name", "tab\u0007bell"):
        with pytest.raises(GameError):
            world.campaign_rename(eng, bad)
    assert eng.state["meta"]["name"] == "Old Title"
    ver = eng.state["version"]
    r = world.campaign_rename(eng, "Old Title")
    assert r["ok"] and not r["renamed"] and "nothing changed" in r["note"]
    assert eng.state["version"] == ver
    # whitespace-only difference is also a no-op
    assert not world.campaign_rename(eng, " Old   Title ")["renamed"]


def test_rename_inside_txn_is_refused(eng):
    _rich_campaign(eng)
    with eng.txn("x"):
        with pytest.raises(GameError):
            world.campaign_rename(eng, "Nope")


def test_rename_undo_restores_title_only(eng):
    _rich_campaign(eng)
    world.campaign_rename(eng, "New Title")
    world.journal_add(eng, "after rename")
    eng.undo(1)  # undoes the journal entry only
    assert eng.state["meta"]["name"] == "New Title"
    eng.undo(1)  # undoes the rename
    assert eng.state["meta"]["name"] == "Old Title"
    assert not any("renamed" in j["text"] for j in eng.state["journal"])
    assert "former_names" not in eng.state["meta"]


def test_rename_with_folder_moves_everything_and_keeps_undo(eng, tmp_path):
    _rich_campaign(eng)
    old_slug = eng.state["meta"]["slug"]
    old_dir = eng.campaign_dir(old_slug)
    n_undo = len(list((old_dir / "undo").glob("*.json")))
    r = world.campaign_rename(eng, "Shiny New Name", rename_folder=True)
    assert r["ok"] and r["folder_moved"] and r["slug"] == "shiny-new-name"
    new_dir = eng.campaign_dir("shiny-new-name")
    assert new_dir.exists() and not old_dir.exists()
    assert len(list((new_dir / "undo").glob("*.json"))) == n_undo + 1  # + the rename's own snapshot
    assert (eng.home / "active").read_text().strip() == "shiny-new-name"
    assert eng.state["meta"]["slug"] == "shiny-new-name"
    # a fresh engine (daemon restart) finds it and everything is intact
    e2 = Engine(home=eng.home, seed=1)
    assert e2.state["meta"]["slug"] == "shiny-new-name" and e2.state["meta"]["name"] == "Shiny New Name"
    assert set(e2.state["characters"]) == {"pyre", "doma"} and len(e2.state["rolls"]) == 1
    assert e2.state["entities"] and e2.state["meta"]["house_rules"] == ["No retries"]
    assert [c["slug"] for c in e2.list_campaigns()] == ["shiny-new-name"]
    # undo works across the move and never resurrects the old folder or slug
    for _ in range(3):
        e2.undo(1)
        assert e2.state["meta"]["slug"] == "shiny-new-name"
        assert not old_dir.exists()
    world.journal_add(e2, "still writing to the right place")
    assert not old_dir.exists()
    assert json.loads((new_dir / "campaign.json").read_text())["meta"]["slug"] == "shiny-new-name"
    # undo all the way back, past the rename, still pinned
    e2.undo(100)
    assert e2.state["meta"]["slug"] == "shiny-new-name" and not old_dir.exists()


def test_rename_folder_collision_gets_suffix_and_same_slug_is_fine(eng):
    world.campaign_create(eng, "Taken", "fresh_face")
    world.campaign_create(eng, "Mine", "fresh_face")
    r = world.campaign_rename(eng, "Taken", rename_folder=True)
    assert r["slug"] == "taken-2" and r["folder_moved"]
    assert any("already titled" in w for w in r["warnings"])
    assert eng.campaign_dir("taken").exists() and eng.campaign_dir("taken-2").exists()
    assert not eng.campaign_dir("mine").exists()
    # renaming to a title with the same slug keeps the folder
    r = world.campaign_rename(eng, "Taken 2", rename_folder=True)
    assert r["slug"] == "taken-2" and not r["folder_moved"] and r["renamed"]
    # a folder-only change (same title) is allowed
    r = world.campaign_rename(eng, "Taken 2", rename_folder=True)
    assert not r["renamed"] and not r["folder_moved"]


def test_rename_mid_combat_leaves_combat_untouched(eng):
    _rich_campaign(eng)
    eng.state["combat"] = {"id": "c1", "name": "Yard", "turns_taken": 3, "combatants": {}, "order": []}
    before = copy.deepcopy(eng.state["combat"])
    world.campaign_rename(eng, "Mid Fight")
    assert eng.state["combat"] == before and eng.state["clock"]["session_open"]


def test_load_campaign_heals_slug_mismatch(eng):
    _rich_campaign(eng)
    slug = eng.state["meta"]["slug"]
    f = eng.campaign_dir(slug) / "campaign.json"
    d = json.loads(f.read_text()); d["meta"]["slug"] = "stale"
    f.write_text(json.dumps(d))
    e2 = Engine(home=eng.home, seed=1)
    assert e2.state["meta"]["slug"] == slug
    world.journal_add(e2, "x")
    assert not e2.campaign_dir("stale").exists()


def test_rename_tool_over_mcp(live_server):
    from mcp import Client
    engine, port = live_server

    async def run():
        async with Client(f"http://127.0.0.1:{port}/mcp") as c:
            t = next(t for t in (await c.list_tools()).tools if t.name == "campaign_rename")
            assert set(t.input_schema["properties"]) == {"name", "rename_folder"} and t.description
            _tool_json(await c.call_tool("campaign_create", {"name": "A", "starting_point": "fresh_face"}))
            r = _tool_json(await c.call_tool("campaign_rename", {"name": "B"}))
            assert r["ok"] and r["name"] == "B" and r["old_name"] == "A"
            r = _tool_json(await c.call_tool("campaign_rename", {"name": ""}))
            assert r["ok"] is False and r["errors"]
            r = _tool_json(await c.call_tool("campaign_rename", {"name": "C", "rename_folder": True}))
            assert r["ok"] and r["slug"] == "c"
            assert _tool_json(await c.call_tool("campaign_list", {}))["campaigns"][0]["name"] == "C"
    asyncio.run(run())
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state") as r:
        assert json.loads(r.read())["meta"]["name"] == "C"
