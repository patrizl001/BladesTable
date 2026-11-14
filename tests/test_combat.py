"""Combat tests. Run against a FakeEngine (section-5 contract) and the real Engine when available."""
from __future__ import annotations

import contextlib
import copy
import random

import pytest

from boe import combat as cm
from boe.combat import GameError

try:
    from boe.engine import Engine as RealEngine
except Exception:  # pragma: no cover
    RealEngine = None


class FakeRoller:
    def __init__(self):
        self.q, self.rng = [], random.Random(7)

    def queue(self, vals):
        self.q.extend(vals)

    def roll(self, n):
        return [self.q.pop(0) if self.q else self.rng.randint(1, 6) for _ in range(n)]


class FakeEngine:
    def __init__(self):
        self.state = {"version": 0, "clock": {"session": 1, "combats": 0}, "characters": {}, "teams": {},
                      "affinity": {}, "journal": [], "rolls": [], "combat": None}
        self.roller = FakeRoller()
        self.depth = 0

    @contextlib.contextmanager
    def txn(self, label):
        if self.depth:
            self.depth += 1
            try:
                yield self.state
            finally:
                self.depth -= 1
            return
        snap = copy.deepcopy(self.state)
        self.depth = 1
        try:
            yield self.state
        except BaseException:
            self.state.clear()
            self.state.update(snap)
            raise
        finally:
            self.depth = 0

    def record_roll(self, **f):
        rec = {"id": f"r{len(self.state['rolls']) + 1}", "mods": [], "dice": []}
        rec.update(f)
        self.state["rolls"].append(rec)
        return rec

    def log(self, text, kind="event", tags=(), gm_only=False):
        e = {"text": text, "kind": kind}
        self.state["journal"].append(e)
        return e

    def require_state(self):
        return self.state


def _char(cid, name, role, team, **kw):
    attrs = {a: 3 for a in ["might", "willpower", "calculation", "gut", "experience", "knowledge", "stamina",
                            "empathy", "attunement", "swiftness", "improvisation", "passion"]}
    attrs.update(kw.pop("attrs", {}))
    arts = kw.pop("arts", None) or [
        {"name": "Spin", "tags": {"potency": 1, "break": 1, "side": 1}},
        {"name": "Press", "tags": {"potency": 1, "topple": 1}},
        {"name": "Lance", "tags": {"potency": 2, "launch": 1, "range": 2}}]
    c = {"id": cid, "name": name, "role": role, "team_id": team, "attributes": attrs, "affinities": ["fire"],
         "arts": arts, "talents": kw.pop("talents", []), "hp": 10, "dead": False, "arc_abilities": {"feeling_it": True},
         "derived": {"max_hp": 10, "initiative_pool": 2, "movement": 3 if role == "bearer" else 1,
                     "basic_range": 1, "max_radius": 3, "start_cooldowns": [0, 2, 4]}}
    c.update(kw)
    return c


GRUNT = {"role": "other", "attack": {"dis": 1, "normal": 1, "adv": 2}, "defense": {"dis": 0, "normal": 1, "adv": 2},
         "hp": 10, "movement": 3, "initiative": 1, "affinities": [], "best_attributes": [], "art_tags": ["break"]}


@pytest.fixture(params=["fake", "real"])
def eng(request, tmp_path):
    if request.param == "fake":
        e = FakeEngine()
    else:
        if RealEngine is None:
            pytest.skip("real engine unavailable")
        e = RealEngine(home=tmp_path, seed=1)
        e.create_campaign("T", "fresh_face")
        e.state["clock"]["session_open"] = True
    st = e.state
    st["characters"] = {
        "pyre": _char("pyre", "Pyre", "bearer", "t1",
                      arts=[{"name": "Spin", "tags": {"potency": 1, "break": 1, "side": 1}},
                            {"name": "Press", "tags": {"potency": 1, "topple": 1}},
                            {"name": "Lance", "tags": {"potency": 2, "launch": 1, "range": 2}},
                            {"name": "Back", "tags": {"potency": 1, "rear": 1}}],
                      attrs={"swiftness": 4}),
        "doma": _char("doma", "Doma", "blade", "t1",
                      arts=[{"name": "Gem", "tags": {"potency": 1, "topple": 1}},
                            {"name": "Pinch", "tags": {"potency": 1, "pincer": 1}},
                            {"name": "x", "tags": {"potency": 1}}]),
        "bridget": _char("bridget", "Bridget", "bearer", "t2"),
        "pandora": _char("pandora", "Pandora", "blade", "t2"),
    }
    st["teams"] = {"t1": {"id": "t1", "bearer": "pyre", "blades": ["doma"]},
                   "t2": {"id": "t2", "bearer": "bridget", "blades": ["pandora"]}}
    return e


def char(e, cid):
    return e.state["characters"][cid]


def cb(e):
    return e.state["combat"]


def C(e, cid):
    return cb(e)["combatants"][cid]


def start(e, extra=None, pcs=("pyre", "doma"), npcs=None, queue=None, mp=None, **kw):
    """Default: pyre [2,2], doma [2,3], grunt [3,2]. Initiative: pyre 2, grunt 1, doma 0."""
    pos = {"pyre": [2, 2], "doma": [2, 3], "bridget": [0, 0], "pandora": [0, 1]}
    ent = [{"char_id": p, "pos": pos[p]} for p in pcs]
    for n in (npcs if npcs is not None else [{"name": "Grunt", "card": GRUNT, "pos": [3, 2]}]):
        ent.append(n)
    ent += extra or []
    init = []
    for p in pcs:
        init += {"pyre": [6, 6], "doma": [1, 1]}.get(p, [1, 1])
    e.roller.queue(queue if queue is not None else init)
    return cm.combat_start(e, "Test", mp or {"width": 8, "height": 8}, ent, **kw)


def become(e, cid):
    cm.combat_adjust(e, [{"op": "set_order", "order": [cid] + [x for x in cb(e)["order"] if x != cid]}])


def cycle(e, n=1):
    for _ in range(n):
        cm.combat_end_turn(e)


def atk(e, who, **kw):
    return cm.combat_attack(e, who, **kw)


def last_roll(e):
    return e.state["rolls"][-1]


# ------------------------------------------------------------ initiative / start
def test_start_order_and_context(eng):
    r = start(eng)
    assert r["ok"] and cb(eng)["order"] == ["pyre", "grunt", "doma"]
    assert "P1^" in r["map"] and "g1v" in r["map"]
    assert r["actor"]["cid"] == "pyre" and r["actor"]["attacks"]
    assert r["special"]["next_level"] == 1
    assert C(eng, "pyre")["cooldowns"][:3] == [0, 2, 4]
    assert any("radius 1 of pyre" in line for line in r["combatants"])


def test_initiative_ties_larger_pool_first(eng):
    char(eng, "doma")["derived"]["initiative_pool"] = 4
    # pyre pool 2 -> 1 success; doma pool 4 -> 1 success; grunt static 1: pool breaks tie, NPC last
    r = start(eng, queue=[5, 1, 5, 1, 1, 1])
    assert cb(eng)["order"] == ["doma", "pyre", "grunt"]


def test_team_order_and_ambush(eng):
    start(eng, queue=[6, 6, 1, 1], team_order={"t1": ["doma", "pyre"]})
    assert cb(eng)["order"][0] == "doma"
    eng.state["combat"] = None
    start(eng, queue=[6, 6, 1, 1], ambush="enemy")
    assert cb(eng)["order"][0] == "grunt"


def test_feeling_it_adds_special_and_attribute(eng):
    start(eng, queue=[1] * 5 + [1, 1], feeling_it=[{"char_id": "pyre", "attribute": "might", "reason": "x"}])
    assert cb(eng)["special"]["points"]["t1"] == 6
    assert char(eng, "pyre")["arc_abilities"]["feeling_it"] is False
    assert eng.state["rolls"][0]["pool"] == 5


def test_cooldown_order_and_ticking(eng):
    start(eng, cooldown_order={"pyre": [1, 0, 2]})
    assert C(eng, "pyre")["cooldowns"][:3] == [2, 0, 4]
    eng.state["combat"] = None
    start(eng)
    eng.roller.queue([5] * 5 + [1])
    atk(eng, "pyre", art=0, target="grunt", attribute="swiftness")
    assert C(eng, "pyre")["cooldowns"][0] == 6
    cm.combat_end_turn(eng)
    assert C(eng, "pyre")["cooldowns"][:3] == [5, 1, 3]
    cycle(eng, 2)
    cm.combat_end_turn(eng)  # pyre again: [4,0,2]
    assert C(eng, "pyre")["cooldowns"][:3] == [4, 0, 2]


# ------------------------------------------------------------ movement
FAR = [{"name": "Grunt", "card": GRUNT, "pos": [7, 7]}]


def test_movement_budgets_and_double_move(eng):
    start(eng, npcs=FAR)
    r = cm.combat_move(eng, "pyre", [3, 3])  # diagonal = 2
    assert r["cost"] == 2 and r["movement_left"] == 4
    r = cm.combat_move(eng, "pyre", [5, 4])  # 3 more
    assert r["movement_left"] == 1 and r["attack_forbidden"]
    with pytest.raises(GameError):
        cm.combat_move(eng, "pyre", [7, 4])  # needs 2, has 1
    with pytest.raises(GameError):
        atk(eng, "pyre", target="grunt", attribute="might", at=None)


def test_attacking_halves_remaining_movement_and_force(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [5, 2]}])
    cm.combat_move(eng, "pyre", [4, 2])  # cost 2, within base 3
    eng.roller.queue([1, 1, 1])
    atk(eng, "pyre", target="grunt", attribute="might")
    assert cm.combat_state(eng, "current")["actor"]["movement"]["left"] == 1  # 3 - 2
    with pytest.raises(GameError):
        cm.combat_move(eng, "pyre", [4, 5])
    r = cm.combat_move(eng, "pyre", [4, 5], force=True)
    assert r["warnings"]


def test_obstacles_and_walls(eng):
    cells = [{"x": 3, "y": y, "type": "wall"} for y in range(0, 4)]
    cm_ = {"width": 8, "height": 8, "cells": cells}
    start(eng, npcs=FAR, mp=cm_, pcs=("pyre",))
    with pytest.raises(GameError):
        cm.combat_move(eng, "pyre", [3, 2])  # wall
    r = cm.combat_move(eng, "pyre", [4, 2])  # around the wall: 6 steps (double move)
    assert r["cost"] == 6


def test_difficult_terrain_costs_double(eng):
    start(eng, npcs=FAR, pcs=("pyre",), mp={"width": 8, "height": 8,
                                           "cells": [{"x": 3, "y": 2, "type": "difficult"}]})
    assert cm.combat_move(eng, "pyre", [3, 2])["cost"] == 2


def test_blade_radius_moves_and_penalties(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [3, 5]}])
    become(eng, "doma")
    r = cm.combat_move(eng, "doma", [2, 5])  # radius 1 -> 3: 2 radius moves (double since no attack)
    assert "attack_forbidden" in r  # used 2 > base 1
    with pytest.raises(GameError):
        atk(eng, "doma", target="grunt", attribute="might")
    # radius 3 attack: -1
    eng.state["combat"] = None
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [3, 5]}])
    C(eng, "doma")["pos"] = [2, 5]
    become(eng, "doma")
    atk(eng, "doma", target="grunt", attribute="might")
    assert last_roll(eng)["pool"] == 2
    assert {"label": "radius 3", "value": -1} in last_roll(eng)["mods"]


def test_blade_outside_max_radius_half_pool(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [3, 6]}])
    C(eng, "doma")["pos"] = [2, 6]  # radius 4 from pyre at [2,2]
    become(eng, "doma")
    atk(eng, "doma", target="grunt", attribute="might", modifier=1)  # 3+1=4 -> half 2
    assert last_roll(eng)["pool"] == 2
    ctx = cm.combat_state(eng, "doma")
    assert any("OUTSIDE" in line for line in ctx["combatants"])


def test_bearer_move_offers_blade_follow(eng):
    start(eng, npcs=FAR)
    r = cm.combat_move(eng, "pyre", [2, 0])  # doma [2,3] now radius 3
    ch = r["blade_radius_change"][0]
    assert ch["from_radius"] == 1 and ch["to_radius"] == 3 and "option" in ch
    r = cm.combat_move(eng, "doma", follow=True)
    assert cm._radius(cb(eng), C(eng, "doma")) == 1
    # forced bearer move: no option
    cm.combat_move(eng, "pyre", [2, 5], forced=True)


def test_forced_move_gives_no_follow_choice(eng):
    start(eng, npcs=FAR)
    r = cm.combat_move(eng, "pyre", [2, 6], forced=True, by="gm")
    assert "option" not in r["blade_radius_change"][0]
    with pytest.raises(GameError):
        cm.combat_move(eng, "doma", follow=True)


# ------------------------------------------------------------ attacks
def test_basic_attack_damage_and_special_and_facing(eng):
    start(eng)
    eng.roller.queue([5, 5, 5, 1])  # might 3 -> 3 dice
    r = atk(eng, "pyre", target="grunt", attribute="might")
    # 3 dice: 5,5,5 = 3 successes vs def 1 -> net 2
    assert r["targets"][0]["damage"] == 2 and C(eng, "grunt")["hp"] == 8
    assert cb(eng)["special"]["points"]["t1"] == 1
    assert C(eng, "pyre")["facing"] == "E" and C(eng, "grunt")["facing"] == "W"
    assert "2 damage" in r["summary"] and "team special 0->1" in r["summary"]
    assert last_roll(eng)["kind"] == "attack" and last_roll(eng)["net"] == 2


def test_near_hit_near_miss_tiers(eng):
    start(eng)
    eng.roller.queue([5, 5, 1])  # 2 successes vs 1 -> near hit
    r = atk(eng, "pyre", target="grunt", attribute="might")
    assert r["targets"][0]["tier"] == "near_hit" and r["targets"][0]["damage"] == 1
    cycle(eng, 3)
    eng.roller.queue([5, 1, 1])  # 1 success vs 1 -> near miss
    r = atk(eng, "pyre", target="grunt", attribute="might")
    assert r["targets"][0]["tier"] == "near_miss" and r["targets"][0]["damage"] == 0
    assert last_roll(eng)["tier"] == "near_miss"


def test_side_positional_art_and_break(eng):
    start(eng)  # grunt faces S; pyre is west -> side
    eng.roller.queue([5] * 3 + [1] * 3)
    r = atk(eng, "pyre", art=0, target="grunt", attribute="swiftness")
    assert last_roll(eng)["pool"] == 6  # 4 + potency 1 + side 1
    assert r["targets"][0]["net"] == 2  # 3 successes - 1
    assert any(s["id"] == "broken" for s in C(eng, "grunt")["statuses"])
    assert "broken" in r["summary"]


def test_rear_bonus_and_front_none(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [3, 4], "facing": "N"}])
    C(eng, "pyre")["pos"] = [3, 5]  # south of grunt who faces N -> rear
    eng.roller.queue([1] * 6)
    atk(eng, "pyre", art=3, target="grunt", attribute="swiftness")
    assert last_roll(eng)["pool"] == 4 + 1 + 2
    cycle(eng, 3)
    C(eng, "grunt")["facing"] = "S"  # attacker south, grunt faces S -> front: no bonus
    eng.roller.queue([1] * 6)
    C(eng, "pyre")["cooldowns"][3] = 0
    atk(eng, "pyre", art=3, target="grunt", attribute="swiftness")
    assert last_roll(eng)["pool"] == 5


def test_pincer_and_negate_positional(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [3, 2]}])
    C(eng, "doma")["pos"] = [4, 4]  # radius 2 from pyre [2,2]; grunt at radius 1
    become(eng, "doma")
    C(eng, "doma")["cooldowns"][1] = 0
    eng.roller.queue([1] * 6)
    atk(eng, "doma", art=1, target="grunt", attribute="might", at=None, force=True)  # out of range 1: forced
    assert last_roll(eng)["pool"] == 3 + 1 + 2
    # negate: NPC bearer with a blade intercepts
    eng.state["combat"] = None
    boss = dict(GRUNT, role="bearer")
    wisp = dict(GRUNT, role="blade", hp=3)
    start(eng, pcs=("pyre",), npcs=[{"name": "Boss", "card": boss, "pos": [5, 5]},
                                    {"name": "Wisp", "card": wisp, "pos": [5, 6], "bearer": "Boss"}])
    C(eng, "pyre")["pos"] = [4, 5]
    eng.roller.queue([1] * 6)
    r = atk(eng, "pyre", art=0, target="boss", attribute="swiftness", negate_positional=True)
    assert last_roll(eng)["pool"] == 5 and C(eng, "wisp")["pos"] == [4, 6]
    assert "intercepts" in r["summary"]


def test_toppled_target_failed_attack_becomes_near_hit(eng):
    start(eng)
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "grunt", "id": "toppled", "remaining": 1,
                            "source": "pyre"}])
    eng.roller.queue([1, 1, 1])
    r = atk(eng, "pyre", target="grunt", attribute="might")
    assert r["targets"][0]["tier"] == "near_hit" and r["targets"][0]["damage"] == 1
    assert last_roll(eng)["auto"] == "topple"


def test_break_then_topple_chain_and_topple_removes_break(eng):
    start(eng)
    eng.roller.queue([5] * 6)
    atk(eng, "pyre", art=0, target="grunt", attribute="swiftness")
    cycle(eng, 2)  # grunt, doma up
    assert cb(eng)["order"][0] == "doma"
    eng.roller.queue([5] * 5)
    r = atk(eng, "doma", art=0, target="grunt", attribute="might", force=True)
    ids = [s["id"] for s in C(eng, "grunt")["statuses"]]
    assert "toppled" in ids and "broken" not in ids
    # topple without break fizzles
    eng.state["combat"] = None
    start(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    eng.roller.queue([5] * 5)
    r = atk(eng, "pyre", art=1, target="grunt", attribute="might")
    assert "toppled" not in [s["id"] for s in C(eng, "grunt")["statuses"]]
    assert any("fizzles" in n for n in r["targets"][0]["notes"])


def _broken(e, cid="grunt"):
    cm.combat_adjust(e, [{"op": "status_add", "cid": cid, "id": "broken", "remaining": 1, "source": "pyre"}])


def test_launch_open_floor_shifts_order_at_end_of_turn(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [3, 2], "facing": "S"}])
    _broken(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 2, "value": 0}])
    eng.roller.queue([5] * 4 + [1] * 2)  # swiftness 4 + potency 2 = 6; 4 succ - 1 = net 3
    atk(eng, "pyre", art=2, target="grunt", attribute="swiftness")
    assert C(eng, "grunt")["pos"] == [6, 2] and C(eng, "grunt")["hp"] == 7
    assert cb(eng)["order"] == ["pyre", "grunt", "doma"]  # shift not yet applied
    cm.combat_end_turn(eng)
    assert cb(eng)["order"] == ["doma", "grunt", "pyre"] or cb(eng)["order"][-1] == "pyre"
    assert cb(eng)["order"].index("grunt") > 0


def test_launch_wall_collision_no_order_shift(eng):
    start(eng, mp={"width": 8, "height": 8, "cells": [{"x": 5, "y": 2, "type": "wall"}]})
    _broken(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 2, "value": 0}])
    eng.roller.queue([5] * 4 + [1] * 2)
    r = atk(eng, "pyre", art=2, target="grunt", attribute="swiftness")
    assert C(eng, "grunt")["pos"] == [4, 2]
    assert C(eng, "grunt")["hp"] == 10 - 3 - 2  # net 3 + collision 2 (remaining squares)
    assert cb(eng)["pending_shifts"] == []


def test_launch_combatant_collision_damages_both(eng):
    other = {"name": "Other", "card": GRUNT, "pos": [5, 2]}
    start(eng, extra=[other])
    _broken(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 2, "value": 0}])
    eng.roller.queue([5] * 4 + [1] * 2)
    atk(eng, "pyre", art=2, target="grunt", attribute="swiftness")
    assert C(eng, "other")["hp"] == 8  # remaining 2
    assert C(eng, "grunt")["hp"] == 10 - 3 - 2
    assert C(eng, "grunt")["pos"] == [6, 2]
    assert cb(eng)["pending_shifts"]


def test_stagger_applies_at_end_of_turn(eng):
    char(eng, "pyre")["arts"][1]["tags"] = {"potency": 1, "stagger": 1}
    start(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    eng.roller.queue([5] * 5)
    atk(eng, "pyre", art=1, target="grunt", attribute="might")
    assert cb(eng)["order"] == ["pyre", "grunt", "doma"]
    cm.combat_end_turn(eng)
    assert cb(eng)["order"] == ["doma", "grunt", "pyre"]


def test_rush_bonus_move(eng):
    char(eng, "pyre")["arts"][1]["tags"] = {"potency": 1, "rush": 2}
    start(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    eng.roller.queue([5] * 5)
    atk(eng, "pyre", art=1, target="grunt", attribute="might")
    assert cm.combat_state(eng, "pyre")["actor"]["movement"]["left"] == 5  # 3 base + 2 rush


# ------------------------------------------------------------ elemental effects
ALLAFF = ["fire", "water", "wind", "ice", "earth", "electricity", "light", "dark"]


def _effect_setup(eng, tags=None):
    char(eng, "pyre")["affinities"] = ALLAFF
    char(eng, "pyre")["arts"][1]["tags"] = tags or {"potency": 1, "unique_effect": 1}
    start(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])


@pytest.mark.parametrize("effect,sid,unit", [
    ("burning_blade", "burning", "own_turns"), ("arts_seal", "arts_seal", "own_turns"),
    ("freezing_force", "frozen", "until_source_turn_start"), ("shadow_manipulation", "shadowed", "own_turns"),
    ("blinding_eclipse", "blinded", "until_source_turn_end")])
def test_detrimental_effects_on_target(eng, effect, sid, unit):
    _effect_setup(eng, {"potency": 1, "unique_effect": 1, "blinding_eclipse": 1} if effect == "blinding_eclipse"
                  else None)
    eng.roller.queue([5] * 5)  # might 3 + 1 = 4 dice? 3+potency 1 -> 4: use 5 queued
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect=effect)
    s = next(x for x in C(eng, "grunt")["statuses"] if x["id"] == sid)
    assert s["unit"] == unit


def test_effect_requires_affinity_and_choice(eng):
    char(eng, "pyre")["arts"][1]["tags"] = {"potency": 1, "unique_effect": 1}
    start(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    with pytest.raises(GameError):
        atk(eng, "pyre", art=1, target="grunt", attribute="might", effect="arts_seal")  # no water
    with pytest.raises(GameError):
        atk(eng, "pyre", art=1, target="grunt", attribute="might")  # must choose
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect="burning_blade")
    assert C(eng, "grunt")["statuses"][0]["id"] == "burning"


def test_burning_ticks_and_expires(eng):
    _effect_setup(eng)
    eng.roller.queue([5] * 4)  # 4 successes vs def 1 -> net 3: burning 3 turns... damage 3
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect="burning_blade")
    hp0 = C(eng, "grunt")["hp"]
    assert next(s for s in C(eng, "grunt")["statuses"] if s["id"] == "burning")["remaining"] == 3
    r = cm.combat_end_turn(eng)  # grunt starts: burn 1
    assert C(eng, "grunt")["hp"] == hp0 - 1 and any("burning" in e for e in r["events"])
    cycle(eng, 3)  # grunt end (->2), doma, pyre
    cm.combat_end_turn(eng)  # pyre ends, grunt starts: burn
    assert C(eng, "grunt")["hp"] == hp0 - 2
    cycle(eng, 1)
    cycle(eng, 2)
    cm.combat_end_turn(eng)
    cycle(eng, 1)
    assert "burning" not in [s["id"] for s in C(eng, "grunt")["statuses"]]
    assert C(eng, "grunt")["hp"] == hp0 - 3


def test_arts_seal_expires_after_target_turn(eng):
    _effect_setup(eng)
    char(eng, "pyre")["affinities"] = ALLAFF
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "doma", "id": "arts_seal", "remaining": 1}])
    cd0 = list(C(eng, "doma")["cooldowns"])
    become(eng, "doma")
    cm.combat_end_turn(eng)
    assert C(eng, "doma")["cooldowns"] == cd0  # frozen
    assert not _has(eng, "doma", "arts_seal")


def _has(e, cid, sid):
    return any(s["id"] == sid for s in C(e, cid)["statuses"])


def test_arts_seal_blocks_art_use(eng):
    start(eng)
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "pyre", "id": "arts_seal", "remaining": 1}])
    with pytest.raises(GameError):
        atk(eng, "pyre", art=0, target="grunt", attribute="might")


def test_frozen_and_broken_expire_at_source_turn_start(eng):
    _effect_setup(eng)
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect="freezing_force")
    _broken(eng)
    assert _has(eng, "grunt", "frozen")
    cycle(eng, 2)  # grunt, doma
    assert _has(eng, "grunt", "frozen")  # still frozen until pyre's turn starts
    cm.combat_end_turn(eng)  # doma ends -> pyre starts
    assert not _has(eng, "grunt", "frozen") and not _has(eng, "grunt", "broken")


def test_broken_reapply_extends_a_cycle(eng):
    start(eng)
    _broken(eng)
    _broken(eng)
    assert next(s for s in C(eng, "grunt")["statuses"] if s["id"] == "broken")["remaining"] == 2


def test_blinded_lasts_through_sources_next_turn(eng):
    _effect_setup(eng, {"potency": 1, "unique_effect": 1, "blinding_eclipse": 1})
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect="blinding_eclipse")
    cycle(eng, 1)  # pyre's own end of turn: still blinded (fresh)
    assert _has(eng, "grunt", "blinded")
    cycle(eng, 2)  # grunt, doma
    assert _has(eng, "grunt", "blinded")  # pyre's next turn not finished
    cycle(eng, 1)  # pyre ends second turn
    assert not _has(eng, "grunt", "blinded")


@pytest.mark.parametrize("effect,sid", [("blustering_gale", "blustering_gale"), ("counter_spike", "counter_spike"),
                                        ("blade_of_light", "blade_of_light"), ("cradling_earth", "cradled")])
def test_support_effects_on_ally(eng, effect, sid):
    _effect_setup(eng, {"potency": 1, "unique_effect": 1, "counter_spike": 1} if effect == "counter_spike" else None)
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect=effect, effect_target="doma")
    assert _has(eng, "doma", sid)


def test_cradled_cleanses_and_blocks(eng):
    _effect_setup(eng)
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "doma", "id": "burning", "remaining": 2}])
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect="cradling_earth", effect_target="doma")
    assert not _has(eng, "doma", "burning") and _has(eng, "doma", "cradled")
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "doma", "id": "burning", "remaining": 2}])
    assert not _has(eng, "doma", "burning")


def test_electrifying_burst_directions(eng):
    _effect_setup(eng)
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect="electrifying_burst")
    cm.combat_end_turn(eng)  # pyre ends; grunt pushed later: order doma first? start [pyre,grunt,doma]
    assert cb(eng)["order"] == ["doma", "grunt", "pyre"]
    eng.state["combat"] = None
    _effect_setup(eng)
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect="electrifying_burst", effect_target="doma")
    cm.combat_end_turn(eng)  # rotate -> grunt, doma, pyre; doma forward -> doma, grunt, pyre
    assert cb(eng)["order"] == ["doma", "grunt", "pyre"]


def test_bitter_snowstorm_and_steam(eng):
    _effect_setup(eng, {"potency": 1, "bitter_snowstorm": 1})
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might")  # single shared tag -> auto
    assert _has(eng, "grunt", "snowstorm")
    eng.state["combat"] = None
    _effect_setup(eng, {"potency": 1, "invigorating_steam": 1})
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "doma", "art": 1, "value": 2}])
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect_target="doma", effect_art=1)
    assert C(eng, "doma")["cooldowns"][1] == 1
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "doma", "art": 1, "value": 0}])
    cycle(eng, 3)
    char(eng, "pyre")["arts"][1]["tags"] = {"potency": 1, "invigorating_steam": 1}
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", effect_target="pyre", effect_art=1)
    assert C(eng, "pyre")["cooldowns"][1] == 6 - 1  # ready art stored the steam bonus: next cooldown starts 1 lower


def test_counter_spike_hurts_attacker(eng):
    start(eng)
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "grunt", "id": "counter_spike", "remaining": 2}])
    eng.roller.queue([5] * 3)
    atk(eng, "pyre", target="grunt", attribute="might")
    assert C(eng, "pyre")["hp"] == 9


def test_healing_potion(eng):
    char(eng, "pyre")["arts"][1]["tags"] = {"potency": 1, "healing_potion": 1}
    start(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0},
                           {"op": "damage", "cid": "doma", "n": 6}])
    eng.roller.queue([5] * 4)  # net 3
    atk(eng, "pyre", art=1, target="grunt", attribute="might", heal_target="doma")
    assert C(eng, "doma")["hp"] == 4 + 3
    # capped at max
    cycle(eng, 3)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    eng.roller.queue([5] * 4)
    atk(eng, "pyre", art=1, target="grunt", attribute="might", heal_target="doma")
    assert C(eng, "doma")["hp"] == 10


# ------------------------------------------------------------ AoE
def _aoe_arts(eng, tags):
    char(eng, "pyre")["arts"][1]["tags"] = tags


def test_circle_hits_allies_unless_precise_spare(eng):
    _aoe_arts(eng, {"potency": 1, "circle": 1})
    start(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    eng.roller.queue([5] * 4 + [1, 1, 1])  # attacker 4 dice (4 succ); doma defends 3 dice: 0 succ
    r = atk(eng, "pyre", art=1, attribute="might", defender_attributes={"doma": "gut"})
    hit = {t["cid"]: t for t in r["targets"]}
    assert set(hit) == {"grunt", "doma"} and hit["doma"]["damage"] == 4 and hit["grunt"]["damage"] == 3
    assert cb(eng)["special"]["points"]["t1"] == 1  # one special point despite two damaged targets
    eng.state["combat"] = None
    _aoe_arts(eng, {"potency": 1, "circle": 1, "precise": 1})
    start(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    eng.roller.queue([5] * 4)
    r = atk(eng, "pyre", art=1, attribute="might", spare=["doma"])
    assert [t["cid"] for t in r["targets"]] == ["grunt"]
    with pytest.raises(GameError):
        eng.state["combat"]["combatants"]["pyre"]["cooldowns"][1] = 0
        _aoe_arts(eng, {"potency": 1, "circle": 1})
        atk(eng, "pyre", art=1, attribute="might", spare=["doma"])


def test_line_attack_direction(eng):
    _aoe_arts(eng, {"potency": 1, "line": 1})
    start(eng, extra=[{"name": "Far", "card": GRUNT, "pos": [6, 2]}])
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    eng.roller.queue([5] * 4)
    r = atk(eng, "pyre", art=1, attribute="might", direction="E")
    assert sorted(t["cid"] for t in r["targets"]) == ["far", "grunt"]


# ------------------------------------------------------------ NPC attacks
def _npc_turn(eng, **kw):
    become(eng, "grunt")
    return cm.combat_npc_attack(eng, "grunt", **kw)


def test_npc_attack_book_examples(eng):
    start(eng, pcs=("pyre",), npcs=[{"name": "Grunt", "card": GRUNT, "pos": [3, 2]}])
    eng.roller.queue([1, 1, 1])  # 0 successes
    r = _npc_turn(eng, targets=["pyre"], level=1, defender_attributes={"pyre": "gut"})
    assert r["targets"][0]["damage"] == 1 and C(eng, "pyre")["hp"] == 9
    assert last_roll(eng)["kind"] == "defense" and last_roll(eng)["check"] == 1
    cycle(eng, 2)
    eng.roller.queue([5, 5, 1])  # 2 successes vs attack 2 -> none
    r = _npc_turn(eng, targets=["pyre"], level=2, defender_attributes={"pyre": "gut"})
    assert r["targets"][0]["damage"] == 0 and r["targets"][0]["tier"] == "near_miss"
    cycle(eng, 2)
    eng.roller.queue([5, 1, 1])  # 1 success vs 2 -> 1 damage
    r = _npc_turn(eng, targets=["pyre"], level=2, defender_attributes={"pyre": "gut"})
    assert r["targets"][0]["damage"] == 1 and C(eng, "pyre")["hp"] == 8


def test_npc_attack_defense_modifiers_and_tags(eng):
    start(eng, pcs=("pyre",))
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "pyre", "id": "blustering_gale", "remaining": 2}])
    eng.roller.queue([1] * 4)
    _npc_turn(eng, targets=["pyre"], level="normal", defender_attributes={"pyre": "gut"}, tags=["break"],
              defender_modifiers={"pyre": 1})
    assert last_roll(eng)["pool"] == 3 + 1 + 1
    assert _has(eng, "pyre", "broken")
    with pytest.raises(GameError):
        cm.combat_npc_attack(eng, "grunt", targets=["pyre"], defender_attributes={})


def test_npc_vs_npc_static(eng):
    ally = {"name": "Guard", "card": GRUNT, "pos": [4, 2], "side": "neutral"}
    start(eng, pcs=("pyre",), extra=[ally])
    C(eng, "grunt")["pos"] = [4, 3]
    r = _npc_turn(eng, targets=["guard"], level=3, ignore_range=False)
    assert r["targets"][0]["damage"] == 2  # 3 - defense 1


def test_npc_toppled_pc_defender_takes_one(eng):
    start(eng, pcs=("pyre",))
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "pyre", "id": "toppled", "remaining": 1}])
    eng.roller.queue([5, 5, 5])
    r = _npc_turn(eng, targets=["pyre"], level=1, defender_attributes={"pyre": "gut"})
    assert r["targets"][0]["damage"] == 1


def test_desperate_defense_and_crisis_catalyst(eng):
    char(eng, "pyre")["talents"] = [{"id": "desperate_defense", "name": "Desperate Defense"},
                                    {"id": "crisis_catalyst", "name": "Crisis Catalyst"}]
    start(eng)
    cm.combat_adjust(eng, [{"op": "set_hp", "cid": "pyre", "n": 2}])
    eng.roller.queue([1] * 5)
    atk(eng, "pyre", target="grunt", attribute="might")
    assert last_roll(eng)["pool"] == 5
    cycle(eng, 1)
    eng.roller.queue([1] * 5)
    cm.combat_npc_attack(eng, "grunt", targets=["pyre"], level=1, defender_attributes={"pyre": "gut"})
    assert last_roll(eng)["pool"] == 5
    ctx = cm.combat_state(eng, "pyre")
    assert any("Crisis Catalyst" in x for x in ctx["actor"]["reminders"])


# ------------------------------------------------------------ specials
def _pts(eng, team, v):
    cm.combat_adjust(eng, [{"op": "special_points", "team_id": team, "value": v}])


def test_special_points_cap_and_display(eng):
    start(eng)
    _pts(eng, "t1", 40)
    assert cb(eng)["special"]["points"]["t1"] == 18
    _pts(eng, "t1", 14)
    assert "6,6,2" in cm.combat_state(eng)["special"]["teams"]["t1"]


def test_special_chain_one_team_consumes_only_at_level_three(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [3, 2]}])
    _pts(eng, "t1", 18)
    eng.roller.queue([5] * 10)
    r = cm.combat_special(eng, "pyre", 1, ideas={"pyre": "justice"}, target="grunt", effect="blinding_eclipse")
    assert r["total"] == 10 and C(eng, "grunt")["hp"] == 0 or C(eng, "grunt")["down"]
    assert cb(eng)["special"]["points"]["t1"] == 18 and cb(eng)["special"]["chain_level"] == 1
    # chain enforcement + new grunt
    cm.combat_adjust(eng, [{"op": "add_combatant", "name": "G2", "card": dict(GRUNT, hp=99), "pos": [3, 3]}])
    cycle(eng, 3)
    assert cb(eng)["order"][0] == "pyre"
    with pytest.raises(GameError):
        cm.combat_special(eng, "pyre", 1, ideas={"pyre": "justice"}, target="g2")
    eng.roller.queue([5] * 20)
    r = cm.combat_special(eng, "pyre", 2, ideas={"pyre": "justice"}, at=[3, 3], effect="blinding_eclipse")
    assert r["total"] == 19 and cb(eng)["special"]["points"]["t1"] == 18
    assert cb(eng)["special"]["chain_level"] == 2
    assert _has(eng, "g2", "blinded") and next(s for s in C(eng, "g2")["statuses"] if s["id"] == "blinded")["remaining"] == 1
    cycle(eng, 3)
    eng.roller.queue([5] * 20)
    cm.combat_special(eng, "pyre", 3, ideas={"pyre": "justice", "doma": "bravery"}, at=[3, 3],
                      effect="burning_blade")
    assert cb(eng)["special"]["points"]["t1"] == 0 and cb(eng)["special"]["chain_level"] == 0


def test_special_needs_points_and_two_team_rules(eng):
    start(eng, pcs=("pyre", "doma", "bridget", "pandora"), queue=[6, 6, 1, 1, 1, 1, 1, 1])
    become(eng, "pyre")
    with pytest.raises(GameError):
        cm.combat_special(eng, "pyre", 1, ideas={"pyre": "justice"}, target="grunt")
    _pts(eng, "t1", 12)
    eng.roller.queue([5] * 5)
    cm.combat_special(eng, "pyre", 1, ideas={"pyre": "justice"}, target="grunt")
    assert cb(eng)["special"]["points"]["t1"] == 6  # consumed in a two-team party
    _pts(eng, "t1", 18)
    cm.combat_adjust(eng, [{"op": "chain_level", "value": 1}])
    cycle(eng, 4)
    become(eng, "pyre")
    eng.roller.queue([5] * 3)
    cm.combat_special(eng, "pyre", 2, ideas={"pyre": "justice"}, at=[3, 2])
    assert cb(eng)["special"]["points"]["t1"] == 6 and cb(eng)["special"]["points"]["t2"] == 6


def test_special_split_pending_and_assign(eng):
    start(eng, extra=[{"name": "G2", "card": GRUNT, "pos": [3, 3]}])
    _pts(eng, "t1", 18)
    cm.combat_adjust(eng, [{"op": "chain_level", "value": 1}])
    eng.roller.queue([5] * 7 + [1] * 13)  # attacker 10 dice: 7 succ; partner 10 dice: 0
    r = cm.combat_special(eng, "pyre", 2, ideas={"pyre": "justice"}, at=[3, 2], effect="blinding_eclipse")
    assert cb(eng)["pending"]["type"] == "special_split" and r["total"] == 7
    with pytest.raises(GameError):
        cm.combat_end_turn(eng)
    with pytest.raises(GameError):
        cm.combat_special_assign(eng, {"grunt": 3, "g2": 3})
    r = cm.combat_special_assign(eng, {"grunt": 4, "g2": 3})
    assert C(eng, "grunt")["hp"] == 6 and C(eng, "g2")["hp"] == 7 and cb(eng)["pending"] is None
    assert next(s for s in C(eng, "grunt")["statuses"] if s["id"] == "blinded")  # duration = share


def test_reconciliation_free_burst(eng):
    start(eng)
    eng.state["affinity"]["doma|pyre"] = -1
    _pts(eng, "t1", 0)
    become(eng, "doma")
    char(eng, "pyre")["attributes"]["passion"] = 1
    eng.roller.queue([5] * 6)
    C(eng, "doma")["pos"] = [3, 3]
    r = cm.combat_special(eng, "doma", 0, ideas={"doma": "justice"}, target="grunt", free_burst=True, partner="pyre")
    assert r["level"] == 1 and cb(eng)["special"]["chain_level"] == 0
    assert eng.state["affinity"]["doma|pyre"] == 0
    with pytest.raises(GameError):
        cm.combat_special(eng, "doma", 0, ideas={"doma": "justice"}, target="grunt", free_burst=True, partner="pyre")


# ------------------------------------------------------------ HP, life force, downs
def _lethal(eng, a_value=3):
    cm.combat_adjust(eng, [{"op": "set_hp", "cid": "pyre", "n": 1}])
    become(eng, "grunt")
    eng.roller.queue([1, 1, 1])
    return cm.combat_npc_attack(eng, "grunt", targets=["pyre"], level=a_value, defender_attributes={"pyre": "gut"})


def test_life_force_sharing_pays_extra_point(eng):
    start(eng)
    r = _lethal(eng)  # pyre 1 - 3 = -2
    assert cb(eng)["pending"]["type"] == "life_force" and not C(eng, "pyre")["down"]
    assert "pending" in r
    with pytest.raises(GameError):
        cm.combat_move(eng, "doma", [2, 4])
    r = cm.combat_life_force(eng, "doma", give=2)
    assert C(eng, "pyre")["hp"] == 2 and C(eng, "doma")["hp"] == 10 - ((2 + 2) + 1)
    assert cb(eng)["pending"] is None


def test_life_force_protective_aegis_no_extra(eng):
    char(eng, "doma")["talents"] = [{"id": "protective_aegis", "name": "Protective Aegis"}]
    start(eng)
    _lethal(eng)
    cm.combat_life_force(eng, "doma", give=2)
    assert C(eng, "doma")["hp"] == 10 - 4


def test_life_force_too_expensive_and_final_flicker(eng):
    char(eng, "doma")["talents"] = [{"id": "final_flicker", "name": "Final Flicker"}]
    start(eng)
    cm.combat_adjust(eng, [{"op": "set_hp", "cid": "doma", "n": 3}])
    _lethal(eng)
    with pytest.raises(GameError):
        cm.combat_life_force(eng, "doma", give=5)
    cm.combat_life_force(eng, "doma", final_flicker=True)
    assert C(eng, "pyre")["hp"] == 1 and C(eng, "doma")["down"]


def test_life_force_decline_downs_bearer_and_blade(eng):
    start(eng)
    _lethal(eng)
    r = cm.combat_life_force(eng, "doma", decline=True)
    assert C(eng, "pyre")["down"] and C(eng, "doma")["down"]
    assert r["suggest_end"] and "pyre" not in cb(eng)["order"]


def test_blade_with_artificial_core_survives_bearer(eng):
    char(eng, "doma")["talents"] = [{"id": "artificial_core", "name": "Artificial Core"}]
    start(eng)
    cm.combat_adjust(eng, [{"op": "down", "cid": "pyre"}])
    assert not C(eng, "doma")["down"]


def test_blade_down_does_not_down_bearer_and_no_life_force_without_blade(eng):
    start(eng)
    cm.combat_adjust(eng, [{"op": "down", "cid": "doma"}])
    assert not C(eng, "pyre")["down"]
    cm.combat_adjust(eng, [{"op": "damage", "cid": "pyre", "n": 20}])
    assert C(eng, "pyre")["down"] and cb(eng)["pending"] is None


def test_enemies_down_suggests_end_and_downed_actor_passes_turn(eng):
    start(eng)
    cm.combat_adjust(eng, [{"op": "set_hp", "cid": "grunt", "n": 1}])
    eng.roller.queue([5] * 3)
    r = atk(eng, "pyre", target="grunt", attribute="might")
    assert r["suggest_end"] and "grunt" not in cb(eng)["order"]


def test_counter_spike_kills_current_actor_passes_turn(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [3, 2]}])
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "grunt", "id": "counter_spike", "remaining": 2},
                           {"op": "remove_combatant", "cid": "doma"}, {"op": "set_hp", "cid": "pyre", "n": 1}])
    eng.roller.queue([5] * 3)
    r = atk(eng, "pyre", target="grunt", attribute="might")
    assert C(eng, "pyre")["down"] and r["turn_passed_to"] == "grunt"


# ------------------------------------------------------------ turn management
def test_swap_turn_and_lock(eng):
    start(eng)
    r = cm.combat_swap_turn(eng, "pyre")
    assert cb(eng)["order"] == ["doma", "grunt", "pyre"] and r["actor"]["cid"] == "doma"
    cm.combat_end_turn(eng)  # doma ends: pyre/doma lock still waits for pyre
    cm.combat_end_turn(eng)  # grunt
    with pytest.raises(GameError):
        cm.combat_swap_turn(eng, "pyre")
    cm.combat_end_turn(eng)  # pyre ends: lock released
    cycle(eng, 2)
    assert cb(eng)["order"][0] == "pyre"
    cm.combat_swap_turn(eng, "pyre")


def test_delay_and_end_turn_must_be_current(eng):
    start(eng)
    with pytest.raises(GameError):
        cm.combat_end_turn(eng, "doma")
    r = cm.combat_delay(eng, "pyre", 1)
    assert cb(eng)["order"][0] == "grunt"
    with pytest.raises(GameError):
        cm.combat_move(eng, "pyre", [2, 1])


def test_toppled_actor_must_skip_and_help_up(eng):
    start(eng)
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "doma", "id": "toppled", "remaining": 1}])
    become(eng, "doma")
    ctx = cm.combat_state(eng, "doma")
    assert ctx["actor"]["must_skip"] and any("toppled" in x for x in ctx["actor"]["reminders"])
    with pytest.raises(GameError):
        cm.combat_move(eng, "doma", [2, 4])
    become(eng, "pyre")
    r = cm.combat_action(eng, "pyre", "help up", kind="help_up", target="doma")
    assert not _has(eng, "doma", "toppled")
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "doma", "id": "toppled", "remaining": 1}])
    become(eng, "doma")
    r = cm.combat_end_turn(eng)  # toppled expires at the end of its own turn
    assert not _has(eng, "doma", "toppled")


def test_combat_action_roll_and_healer(eng):
    char(eng, "pyre")["talents"] = [{"id": "healer", "name": "Healer"}]
    start(eng)
    r = None
    eng.roller.queue([5, 5, 1])
    r = cm.combat_action(eng, "pyre", "kick the door", attribute="might", check=1)
    assert r["tier"] == "near_hit" and last_roll(eng)["net"] == 1
    cycle(eng, 3)
    cm.combat_adjust(eng, [{"op": "damage", "cid": "doma", "n": 5}, {"op": "cooldown", "cid": "pyre", "art": 1, "value": 0}])
    eng.roller.queue([5, 5, 5, 1])
    r = cm.combat_action(eng, "pyre", "heal", attribute="might", kind="heal", art=1, target="doma")
    assert C(eng, "doma")["hp"] == 5 + 3 and C(eng, "pyre")["cooldowns"][1] == 6
    assert C(eng, "pyre")["cooldowns"][0] == 6 - 0  # the other ready art was reset (Healer cost)


# ------------------------------------------------------------ adjust / end / force / misc
def test_adjust_ops(eng):
    start(eng)
    r = cm.combat_adjust(eng, [
        {"op": "damage", "cid": "grunt", "n": 2}, {"op": "heal", "cid": "grunt", "n": 1},
        {"op": "status_add", "cid": "grunt", "id": "burning", "remaining": 2},
        {"op": "status_remove", "cid": "grunt", "id": "burning"}, {"op": "move", "cid": "grunt", "to": [6, 6]},
        {"op": "face", "cid": "grunt", "dir": "N"}, {"op": "shift_order", "cid": "doma", "delta": 1},
        {"op": "cell", "x": 1, "y": 1, "type": "hazard", "label": "lava"},
        {"op": "card", "cid": "grunt", "patch": {"defense": {"normal": 3}}},
        {"op": "cooldown", "cid": "pyre", "art": 0, "value": 3}], reason="test")
    assert C(eng, "grunt")["hp"] == 9 and C(eng, "grunt")["pos"] == [6, 6] and C(eng, "grunt")["facing"] == "N"
    assert cb(eng)["order"] == ["pyre", "doma", "grunt"]
    assert cb(eng)["map"]["cells"]["1,1"]["type"] == "hazard"
    assert C(eng, "grunt")["card"]["defense"]["normal"] == 3 and C(eng, "pyre")["cooldowns"][0] == 3
    with pytest.raises(GameError):
        cm.combat_adjust(eng, [{"op": "bogus"}])
    cm.combat_adjust(eng, [{"op": "down", "cid": "grunt"}, {"op": "revive", "cid": "grunt", "hp": 2}])
    assert C(eng, "grunt")["hp"] == 2 and "grunt" in cb(eng)["order"]


def test_combat_end_restores_hp_and_logs(eng):
    char(eng, "pyre")["talents"] = [{"id": "x", "name": "X", "per": "combat", "used": True}]
    start(eng)
    cm.combat_adjust(eng, [{"op": "damage", "cid": "pyre", "n": 4}])
    r = cm.combat_end(eng, "victory", "grunt fled", restore_hp=False)
    assert char(eng, "pyre")["hp"] == 6 and eng.state["combat"] is None
    assert eng.state["clock"]["combats"] == 1 and eng.state["journal"]
    assert char(eng, "pyre")["talents"][0]["used"] is False
    start(eng)
    cm.combat_adjust(eng, [{"op": "damage", "cid": "pyre", "n": 4}])
    cm.combat_end(eng, "victory")
    assert char(eng, "pyre")["hp"] == 10


def test_pc_hp_comes_from_character_and_errors_rollback(eng):
    char(eng, "pyre")["hp"] = 4
    start(eng)
    assert C(eng, "pyre")["hp"] == 4
    snap = copy_state(eng)
    with pytest.raises(GameError):
        atk(eng, "pyre", target="grunt", attribute="bogus")
    assert copy_state(eng) == snap


def copy_state(eng):
    import json
    return json.dumps(eng.state, sort_keys=True, default=str)


def test_force_overrides_range_and_turn(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [6, 6]}])
    with pytest.raises(GameError):
        atk(eng, "pyre", target="grunt", attribute="might")
    eng.roller.queue([5] * 3)
    r = atk(eng, "pyre", target="grunt", attribute="might", force=True)
    assert r["warnings"]
    with pytest.raises(GameError):
        atk(eng, "doma", target="grunt", attribute="might")
    with pytest.raises(GameError):
        cm.combat_start(eng, "again", {"width": 3, "height": 3}, [])


def test_los_blocked_by_wall(eng):
    start(eng, npcs=[{"name": "Grunt", "card": GRUNT, "pos": [4, 2]}], pcs=("pyre",),
          mp={"width": 8, "height": 8, "cells": [{"x": 3, "y": 2, "type": "wall"}]})
    char(eng, "pyre")["derived"]["basic_range"] = 3
    C(eng, "pyre")["pos"] = [2, 2]
    with pytest.raises(GameError):
        atk(eng, "pyre", target="grunt", attribute="might")


def test_bestiary_reference(eng, monkeypatch):
    monkeypatch.setattr(cm, "_load_bestiary", lambda: {"pack_animal": dict(GRUNT, name="Pack Animal")})
    start(eng, npcs=[{"bestiary": "pack_animal", "pos": [3, 2]}, {"bestiary": "pack_animal", "pos": [4, 2]}])
    assert "pack_animal_1" in cb(eng)["combatants"] or "pack_animal_2" in cb(eng)["combatants"]
    names = sorted(c["name"] for c in cb(eng)["combatants"].values() if c["kind"] == "npc")
    assert names == ["Pack Animal 1", "Pack Animal 2"]
    monkeypatch.setattr(cm, "_load_bestiary", lambda: None)
    eng.state["combat"] = None
    with pytest.raises(GameError):
        start(eng, npcs=[{"bestiary": "pack_animal", "pos": [3, 2]}])


def test_dirty_fighter_bonus(eng):
    char(eng, "pyre")["talents"] = [{"id": "dirty_fighter", "name": "Dirty Fighter"}]
    start(eng)
    cm.combat_adjust(eng, [{"op": "status_add", "cid": "grunt", "id": "toppled", "remaining": 1}])
    eng.roller.queue([5] * 3)  # 3 succ vs 1 = net 2, +1
    r = atk(eng, "pyre", target="grunt", attribute="might")
    assert r["targets"][0]["damage"] == 3


def test_tools_register():
    from boe import tools_combat
    from mcp.server.mcpserver import MCPServer
    m = MCPServer("t")
    tools_combat.register(m, FakeEngine())
    import asyncio
    names = {t.name for t in asyncio.run(m.list_tools())}
    assert {"combat_start", "combat_attack", "combat_end", "combat_special", "combat_adjust"} <= names
    out = asyncio.run(m.call_tool("combat_state", {}))
    assert "errors" in str(out)


# ------------------------------------------------------------ integration-playtest regressions
def test_pending_error_names_the_tool_and_result_has_next(eng):
    start(eng)
    r = _lethal(eng)
    assert "combat_life_force" in r["next"]
    for call in (lambda: cm.combat_end_turn(eng), lambda: cm.combat_move(eng, "doma", [2, 4])):
        with pytest.raises(GameError) as ei:
            call()
        assert "combat_life_force" in str(ei.value)
    assert "combat_life_force" in cm.combat_state(eng)["next"]


def test_special_split_pending_error_names_assign_tool(eng):
    start(eng, extra=[{"name": "G2", "card": GRUNT, "pos": [3, 3]}])
    _pts(eng, "t1", 18)
    cm.combat_adjust(eng, [{"op": "chain_level", "value": 1}])
    eng.roller.queue([5] * 7 + [1] * 13)
    r = cm.combat_special(eng, "pyre", 2, ideas={"pyre": "justice"}, at=[3, 2], effect="blinding_eclipse")
    assert "combat_special_assign" in r["next"]
    with pytest.raises(GameError) as ei:
        cm.combat_end_turn(eng)
    assert "combat_special_assign" in str(ei.value)


def test_fiat_move_cannot_stack_or_enter_walls_and_revive_relocates(eng):
    start(eng, mp={"width": 8, "height": 8, "cells": [{"x": 5, "y": 5, "type": "wall"}]})
    with pytest.raises(GameError):
        cm.combat_adjust(eng, [{"op": "move", "cid": "grunt", "to": [2, 3]}])        # doma stands there
    with pytest.raises(GameError):
        cm.combat_adjust(eng, [{"op": "move", "cid": "grunt", "to": [5, 5]}])        # wall
    cm.combat_adjust(eng, [{"op": "down", "cid": "grunt"}])
    cm.combat_adjust(eng, [{"op": "move", "cid": "doma", "to": [3, 2]}])             # onto the downed grunt's square: fine
    cm.combat_adjust(eng, [{"op": "revive", "cid": "grunt", "hp": 3}])
    pos = [tuple(c["pos"]) for c in cb(eng)["combatants"].values() if not c["down"]]
    assert len(pos) == len(set(pos)) and C(eng, "grunt")["pos"] != [3, 2]


def test_combat_state_suggests_end_when_enemies_down(eng):
    start(eng)
    cm.combat_adjust(eng, [{"op": "down", "cid": "grunt"}])
    assert cm.combat_state(eng).get("suggest_end") is True


def test_fiat_cooldown_is_clamped_to_0_6(eng):
    start(eng)
    cm.combat_adjust(eng, [{"op": "cooldown", "cid": "pyre", "art": 0, "value": 9}, {"op": "cooldown", "cid": "pyre", "art": 1, "value": -3}])
    assert C(eng, "pyre")["cooldowns"][:2] == [6, 0]
