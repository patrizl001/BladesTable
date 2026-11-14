"""Combat part of the blind playtest (MCP-only). Imported by playtest.py."""
import json, random
from playtest_common import check, friction, pick

HERO, BLADE = "kael-varrow", "vesper"
MAXDIST = lambda a, b: abs(a[0] - b[0]) + abs(a[1] - b[1])


class CT:
    """Combat tester: wraps tool calls, re-reads the authoritative state through get_state('full'),
    and asserts structural invariants after every call."""

    def __init__(self, t, rng=None, verbose=True):
        self.t, self.rng, self.verbose = t, rng or random.Random(1), verbose
        self.c = None
        self.chars = {}
        self.calls = 0

    # ---- state
    async def sync(self):
        r = await self.t("get_state", scope="full", quiet=True)
        st = r.get("state", {})
        self.chars = st.get("characters", {})
        self.c = st.get("combat")
        self.full = st
        return self.c

    def co(self, cid):
        return self.c["combatants"][cid]

    def living(self, side=None):
        return [c for c in self.c["combatants"].values() if not c["down"] and (side is None or c["side"] == side)]

    def actor(self):
        return self.c["order"][0] if self.c and self.c["order"] else None

    def snap(self):
        if not self.c:
            return {}
        return {k: {"hp": v["hp"], "pos": list(v["pos"]), "cd": list(v.get("cooldowns") or []), "down": v["down"],
                    "st": [(s["id"], s["remaining"]) for s in v["statuses"]]} for k, v in self.c["combatants"].items()} | \
            {"_special": json.loads(json.dumps(self.c["special"])), "_order": list(self.c["order"])}

    # ---- invariants
    def invariants(self, ctx=""):
        c = self.c
        if c is None:
            return
        m = c["map"]
        W, H = m["width"], m["height"]
        seen = {}
        for cid, v in c["combatants"].items():
            x, y = v["pos"]
            check(0 <= x < W and 0 <= y < H, f"{ctx}: {cid} out of bounds {v['pos']}")
            if not v["down"]:
                key = (x, y)
                check(key not in seen, f"{ctx}: {cid} and {seen.get(key)} share square {key}")
                seen[key] = cid
                cell = m["cells"].get(f"{x},{y}")
                check(not (cell and cell.get("blocks_move", cell["type"] in ("wall", "obstacle", "cover"))),
                      f"{ctx}: {cid} standing on blocking terrain {cell} at {key}")
            pend_lf = (c.get("pending") or {}).get("type") == "life_force" and (c["pending"].get("bearer") == cid or any(
                p_.get("bearer") == cid for p_ in c.get("pending_more", [])))
            check((0 if not pend_lf else -99) <= v["hp"] <= v["max_hp"], f"{ctx}: {cid} hp {v['hp']}/{v['max_hp']} out of range")
            if v["kind"] == "npc":
                check((v["hp"] == 0) == v["down"], f"{ctx}: npc {cid} hp {v['hp']} down={v['down']}")
            if v["down"]:
                check(cid not in c["order"], f"{ctx}: downed {cid} still in order")
            else:
                if v["kind"] == "pc" and v["hp"] <= 0:
                    check(bool(c.get("pending")), f"{ctx}: living pc {cid} at 0 hp with no pending")
            if v.get("cooldowns") is not None and v["kind"] == "pc":
                check(len(v["cooldowns"]) == 3 and all(isinstance(d, int) and 0 <= d <= 6 for d in v["cooldowns"]),
                      f"{ctx}: {cid} cooldowns {v['cooldowns']}")
            for s in v["statuses"]:
                check(1 <= s["remaining"] <= 6, f"{ctx}: {cid} status {s} remaining out of 1..6")
        living = {cid for cid, v in c["combatants"].items() if not v["down"]}
        check(len(c["order"]) == len(set(c["order"])), f"{ctx}: duplicate in order {c['order']}")
        check(set(c["order"]) == living, f"{ctx}: order {c['order']} != living {sorted(living)}")
        sp = c["special"]
        check(0 <= sp["chain_level"] <= 3, f"{ctx}: chain_level {sp['chain_level']}")
        for tid, p in sp["points"].items():
            check(0 <= p <= 18, f"{ctx}: team {tid} points {p}")

    # ---- calling
    async def __call__(self, tool, /, quiet=None, expect_ok=None, **a):
        q = (not self.verbose) if quiet is None else quiet
        r = await self.t(tool, quiet=q, **a)
        self.calls += 1
        check(isinstance(r, dict) and isinstance(r.get("ok"), bool), f"{tool}: result lacks ok bool: {str(r)[:120]}")
        if r.get("ok") is False:
            errs = r.get("errors")
            check(isinstance(errs, list) and errs and all(isinstance(e, str) and e for e in errs), f"{tool}: ok=false without errors list: {str(r)[:150]}")
        if expect_ok is True:
            check(r.get("ok") is True, f"{tool}({json.dumps(a)[:150]}) expected ok: {r.get('errors')}")
        if expect_ok is False:
            check(r.get("ok") is False, f"{tool}({json.dumps(a)[:150]}) expected failure but ok")
        if tool.startswith("combat_") or tool == "undo":
            await self.sync()
            self.invariants(f"after {tool}")
            if self.c and self.c.get("pending") and r.get("ok"):
                check("pending" in r or "next" in r or "pending" in json.dumps(r), f"{tool}: pending set but result does not say so: {str(r)[:200]}")
        return r

    # ---- helpers
    def free_cells_near(self, pos, maxd=3):
        W, H = self.c["map"]["width"], self.c["map"]["height"]
        occ = {tuple(v["pos"]) for v in self.c["combatants"].values() if not v["down"]}
        out = []
        for dx in range(-maxd, maxd + 1):
            for dy in range(-maxd, maxd + 1):
                p = (pos[0] + dx, pos[1] + dy)
                if (dx or dy) and 0 <= p[0] < W and 0 <= p[1] < H and p not in occ:
                    cell = self.c["map"]["cells"].get(f"{p[0]},{p[1]}")
                    if cell and cell.get("blocks_move", cell["type"] in ("wall", "obstacle", "cover")):
                        continue
                    out.append(list(p))
        out.sort(key=lambda p: abs(p[0] - pos[0]) + abs(p[1] - pos[1]))
        return out

    def nearest(self, cid, side):
        me = self.co(cid)["pos"]
        cands = [c for c in self.living(side)]
        if not cands:
            return None
        return min(cands, key=lambda c: MAXDIST(me, c["pos"]))

    async def step_towards(self, cid, target_pos, want_dist=1):
        """try combat_move to cells nearer the target until one is accepted. returns True if moved."""
        me = self.co(cid)
        cells = self.free_cells_near(me["pos"], 4)
        cells = [p for p in cells if MAXDIST(p, target_pos) >= want_dist]
        cells.sort(key=lambda p: (abs(MAXDIST(p, target_pos) - want_dist), MAXDIST(p, me["pos"])))
        for p in cells[:4]:
            r = await self("combat_move", cid=cid, to=p, quiet=True)
            if r.get("ok"):
                return r
        return None

    async def end_turn(self, cid=None, **kw):
        cid = cid or self.actor()
        return await self("combat_end_turn", cid=cid, facing=self.rng.choice("NESW"), **kw)

    # ---- one generic automatic turn (used for filler turns and fuzzing)
    async def auto_turn(self, mode="smart"):
        cid = self.actor()
        me = self.co(cid)
        if me.get("pending") or self.c.get("pending"):
            await self.resolve_pending()
            return
        foe_side = "enemy" if me["side"] == "party" else "party"
        foe = self.nearest(cid, foe_side)
        if foe is None:
            return
        if me["kind"] == "npc":
            rng_ = (me["card"] or {}).get("range", 1)
            if MAXDIST(me["pos"], foe["pos"]) > rng_:
                await self.step_towards(cid, foe["pos"], 1)
                me = self.co(cid)
            if MAXDIST(me["pos"], foe["pos"]) <= rng_:
                tgt = foe["cid"]
                lvl = self.rng.choice(["dis", "normal", "normal", "adv", 3])
                args = dict(attacker=cid, targets=[tgt], level=lvl, label="strikes")
                if foe["kind"] == "pc":
                    args["defender_attributes"] = {tgt: self.rng.choice(["swiftness", "stamina", "might", "willpower"])}
                if self.rng.random() < 0.3:
                    args["tags"] = [self.rng.choice(["break", "topple", "launch", "stagger", "rush"])]
                await self("combat_npc_attack", quiet=True, **args)
            await self.resolve_pending()
            await self.end_turn(cid)
        else:
            if MAXDIST(me["pos"], foe["pos"]) > 1:
                await self.step_towards(cid, foe["pos"], 1)
                me = self.co(cid)
            foe = self.nearest(cid, foe_side) or foe
            await self.pc_attack_something(cid, foe)
            await self.resolve_pending()
            await self.end_turn(cid)

    async def pc_attack_something(self, cid, foe):
        me = self.co(cid)
        ready = [i for i, d in enumerate(me["cooldowns"]) if d == 0]
        ch = self.chars[me["char_id"]]
        attr_pool = ["might", "swiftness", "willpower", "stamina", "improvisation"]
        opts = ["basic"] + [("art", i) for i in ready]
        pick_ = self.rng.choice(opts)
        a = dict(attacker=cid, attribute=self.rng.choice(attr_pool), label="attacks")
        if pick_ == "basic":
            a.update(kind="basic", target=foe["cid"])
        else:
            i = pick_[1]
            tags = ch["arts"][i]["tags"]
            a.update(kind="art", art=i)
            if "circle" in tags:
                a["at"] = list(me["pos"])
            elif "healing_potion" in tags:
                a["heal_target"] = self.rng.choice([HERO, BLADE])
                a["target"] = foe["cid"]
            else:
                a["target"] = foe["cid"]
            if "unique_effect" in tags:
                els = {"fire": "burning_blade", "water": "arts_seal"}
                a["effect"] = els.get(ch["affinities"][0])
        # allies in a circle must defend as PCs
        defs = {c["cid"]: self.rng.choice(["swiftness", "stamina"]) for c in self.living("party") if c["cid"] != cid}
        a["defender_attributes"] = defs
        return await self("combat_attack", quiet=True, **a)

    async def resolve_pending(self, decline_p=0.0):
        for _ in range(3):
            p = self.c.get("pending")
            if not p:
                return
            if p["type"] == "life_force":
                if self.rng.random() < decline_p:
                    await self("combat_life_force", decline=True, quiet=True)
                else:
                    await self("combat_life_force", give=self.rng.choice([1, 2, 3]), quiet=True)
            elif p["type"] == "special_split":
                tot = p.get("total") or p.get("damage") or 0
                tg = p.get("targets") or p.get("candidates") or []
                tg = [t if isinstance(t, str) else t.get("cid") for t in tg]
                if tg:
                    alloc = {tg[0]: tot}
                    await self("combat_special_assign", allocations=alloc, quiet=True)
                else:
                    await self("combat_special_assign", allocations={}, force=True, quiet=True)
            else:
                return


# ====================================================================== scripted story combat
CARD = {"role": "bearer", "attack": {"dis": 1, "normal": 2, "adv": 3}, "defense": {"dis": 0, "normal": 1, "adv": 2},
        "hp": 7, "movement": 3, "initiative": 4, "affinities": ["fire"], "range": 1,
        "special_abilities": [{"name": "Rally", "text": "Allies near gain heart"}]}
CELLS = [{"x": 4, "y": 1, "type": "wall"}, {"x": 4, "y": 2, "type": "wall", "label": "collapsed wall"},
         {"x": 5, "y": 5, "type": "obstacle", "label": "crate"}, {"x": 3, "y": 6, "type": "cover", "label": "barrel"},
         {"x": 6, "y": 2, "type": "hazard", "label": "vent"}, {"x": 2, "y": 5, "type": "difficult", "label": "rubble"}]


async def retry_undo(ct, make_call, ok_pred, tries=25, what=""):
    """Run make_call(); if ok_pred(result) is false, undo (which reverts dice) and re-run. Returns the accepted result."""
    r = None
    for i in range(tries):
        r = await make_call()
        if r.get("ok") and ok_pred(r):
            return r
        if r.get("ok") is False:
            check(False, f"{what}: call errored (not retrying): {r.get('errors')}")
            return r
        u = await ct("undo", steps=1, quiet=True)
        check(u.get("ok"), f"undo failed while retrying {what}: {u}")
    check(False, f"could not reach desired outcome for {what} in {tries} tries; last={str(r)[:200]}")
    return r


def targets_of(r):
    return {t["cid"]: t for t in r.get("targets", [])}


async def scripted_combat(t, rng):
    print("\n===== PART 3: scripted combat =====")
    ct = CT(t, rng)
    st = await t("get_state", scope="summary", quiet=True)
    check(st.get("combat") is None, "no combat active at start")
    r = await ct("combat_start", name="Yard fight", map={"width": 10, "height": 8, "name": "Rustwharf yard", "cells": CELLS},
                 combatants=[
                     {"char_id": HERO, "pos": [1, 3], "facing": "E"}, {"char_id": BLADE, "pos": [1, 4]},
                     {"name": "Pack Animal", "bestiary": "pack_animal", "pos": [6, 3]},
                     {"name": "Pack Animal", "bestiary": "pack_animal", "pos": [6, 4]},
                     {"name": "Pack Animal", "bestiary": "pack_animal", "pos": [7, 3]},
                     {"name": "Cinder Captain", "card": CARD, "pos": [8, 5]},
                     {"name": "Cinder Edge", "card": dict(CARD, role="blade", hp=6), "bearer": "Cinder Captain", "pos": [7, 5]}],
                 feeling_it=[{"char_id": HERO, "attribute": "swiftness", "reason": "burning to prove himself"}], expect_ok=True)
    await ct.sync()
    check(len(ct.c["order"]) == 7, "7 combatants in order")
    check(ct.c["special"]["points"]["t_kael-varrow"] == 6, "feeling_it gives 6 special points")
    check(ct.co("pack_animal_2")["card"]["hp"] == 5 and ct.co("cinder_edge")["bearer_cid"] == "cinder_captain", "bestiary + blade pairing")
    check(len(ct.co(HERO)["cooldowns"]) == 3 and ct.co(HERO)["cooldowns"] == [0, 2, 4], f"start cooldowns {ct.co(HERO)['cooldowns']}")

    async def to_turn(cid, limit=20):
        n = 0
        while ct.actor() != cid and n < limit and len(ct.living("enemy")):
            a = ct.actor()
            if ct.co(a)["kind"] == "npc":
                await ct.auto_turn()
            else:
                await ct.end_turn(a)
            n += 1
        check(ct.actor() == cid, f"could not reach {cid}'s turn (actor={ct.actor()})")

    async def stage(extra=()):
        ops = [{"op": "move", "cid": "pack_animal_3", "to": [6, 1]}, {"op": "move", "cid": "cinder_captain", "to": [8, 6]},
               {"op": "move", "cid": "cinder_edge", "to": [7, 6]},
               {"op": "move", "cid": "pack_animal_1", "to": [3, 3]}, {"op": "move", "cid": "pack_animal_2", "to": [3, 4]},
               {"op": "move", "cid": HERO, "to": [1, 3]}, {"op": "move", "cid": BLADE, "to": [1, 4]}]
        for c in (HERO, BLADE):
            for a in range(3):
                ops.append({"op": "cooldown", "cid": c, "art": a, "value": 0})
        return await ct("combat_adjust", ops=ops + list(extra), reason="stage the fight", expect_ok=True)

    await to_turn(HERO)
    await stage()
    check(ct.co("pack_animal_1")["pos"] == [3, 3], "fiat move applied")

    # ---------------- Kael: movement rules
    r = await ct("combat_move", cid=HERO, to=[9, 7], expect_ok=False)
    check(any("movement" in e.lower() for e in r["errors"]), f"too-far move error not actionable: {r['errors']}")
    await ct("combat_move", cid=HERO, to=[4, 2], expect_ok=False)
    await ct("combat_move", cid=HERO, to=[3, 3], expect_ok=False)
    r = await ct("combat_move", cid=HERO, to=[2, 3], expect_ok=True)
    check(r.get("cost") == 1 and r.get("movement_left") == 7, f"move cost {r}")
    # sprint: base movement 4 (Quick Step); total moved > 4 forbids attacking
    r = await ct("combat_move", cid=HERO, to=[2, 7], expect_ok=True)
    mv = ct.co(HERO)["turn"]["moved"]
    check(mv > 4, f"sprinted past base: moved={mv}")
    r = await ct("combat_attack", attacker=HERO, attribute="might", target="pack_animal_1", expect_ok=False)
    check(any("mov" in e.lower() or "sprint" in e.lower() for e in r["errors"]), f"attack after sprint error should mention movement: {r['errors']}")
    r = await ct("undo", steps=2, expect_ok=True)       # undoes the sprint and the 1-square move
    await ct.sync()
    check(ct.co(HERO)["pos"] == [1, 3], f"undo restored position, got {ct.co(HERO)['pos']}")
    r = await ct("combat_move", cid=HERO, to=[2, 3], expect_ok=True)
    # blade: radius change info when bearer moved (bearer 1,3 -> 2,3: radius stays 1)
    await ct.sync()

    # ---------------- Cleaver (break, side)
    before = ct.snap()
    r = await retry_undo(ct, lambda: ct("combat_attack", attacker=HERO, attribute="might", kind="art", art=1, target="pack_animal_1",
                                        label="Cleaver"), lambda r: targets_of(r).get("pack_animal_1", {}).get("damage", 0) > 0, what="Cleaver hit")
    tr = targets_of(r)["pack_animal_1"]
    now = ct.co("pack_animal_1")
    check(now["hp"] == before["pack_animal_1"]["hp"] - tr["damage"], f"hp drop == reported damage: {before['pack_animal_1']['hp']} - {tr['damage']} != {now['hp']}")
    check(any(s["id"] == "broken" for s in now["statuses"]), "break applied 'broken'")
    check(ct.co(HERO)["cooldowns"][1] == 5, f"Cleaver cooldown 6-1=5, got {ct.co(HERO)['cooldowns']}")
    pts = ct.c["special"]["points"]["t_kael-varrow"]
    check(pts == before["_special"]["points"]["t_kael-varrow"] + 1, f"special +1 after damaging attack: {pts}")
    r = await ct("combat_attack", attacker=HERO, attribute="might", kind="art", art=2, target="pack_animal_1", expect_ok=False)
    check(any("action" in e.lower() or "already" in e.lower() or "used" in e.lower() for e in r["errors"]), f"second action error: {r['errors']}")
    await ct("combat_end_turn", cid=BLADE, expect_ok=False)
    await ct("combat_end_turn", cid=HERO, facing="E", expect_ok=True)
    check(ct.co(HERO)["cooldowns"] == [0, 4, 0] or ct.co(HERO)["cooldowns"][1] == 4, f"cooldown tick: {ct.co(HERO)['cooldowns']}")

    # ---------------- NPC attacks with player defense rolls
    await to_turn("pack_animal_1")
    r = await ct("combat_npc_attack", attacker="pack_animal_1", targets=[HERO], level="normal", label="lunges", expect_ok=None)
    if r.get("ok") is False:
        friction("combat_npc_attack without defender_attributes: error was: %s" % r["errors"])
        check(any("defender_attributes" in e for e in r["errors"]), "error should name defender_attributes")
    hp_k = ct.co(HERO)["hp"]
    r = await ct("combat_npc_attack", attacker="pack_animal_1", targets=[HERO], level="normal", label="lunges",
                 defender_attributes={HERO: "swiftness"}, expect_ok=True)
    tr = targets_of(r).get(HERO)
    check(tr is not None, "npc attack target result")
    if tr:
        check(ct.co(HERO)["hp"] == hp_k - tr["damage"], f"PC hp drop == damage {tr}")
    await ct("combat_end_turn", cid="pack_animal_1", facing="W")

    # ---------------- Blade radius + Break -> Topple + Launch into wall
    await to_turn(BLADE)
    await ct.sync()
    kp = ct.co(HERO)["pos"]
    far = [kp[0] + 3, kp[1]]
    r = await ct("combat_move", cid=BLADE, to=[kp[0] + 3, kp[1] + 3], expect_ok=None)       # radius 3
    check(r.get("ok"), f"blade double radius move (not attacking): {r.get('errors')}")
    blade_moved = bool(r.get("ok"))
    r = await ct("combat_move", cid=BLADE, to=[kp[0] + 5, kp[1]], expect_ok=False)          # beyond max radius
    await ct.sync()
    if blade_moved:
        await ct("undo", steps=1, expect_ok=True)    # revert so the blade can still attack this turn
    # launch into the wall at (4,2): blade at (2,2) facing E, broken target at (3,2)
    await ct("combat_adjust", ops=[{"op": "move", "cid": "pack_animal_1", "to": [3, 5]},
                                   {"op": "move", "cid": BLADE, "to": [2, 2]}, {"op": "move", "cid": "pack_animal_2", "to": [3, 2]},
                                   {"op": "status_add", "cid": "pack_animal_2", "id": "broken", "remaining": 3, "source": HERO},
                                   {"op": "hp_full", "cid": "pack_animal_2"}] if False else
                    [{"op": "move", "cid": "pack_animal_1", "to": [3, 5]}, {"op": "move", "cid": BLADE, "to": [2, 2]},
                     {"op": "move", "cid": "pack_animal_2", "to": [3, 2]},
                     {"op": "status_add", "cid": "pack_animal_2", "id": "broken", "remaining": 3, "source": HERO},
                     {"op": "set_hp", "cid": "pack_animal_2", "n": 5}], expect_ok=True)
    hp_before = ct.co("pack_animal_2")["hp"]
    print('   STAGED p2:', ct.co('pack_animal_2')['pos'], ct.co('pack_animal_2')['statuses'], 'actor', ct.actor())
    r = await retry_undo(ct, lambda: ct("combat_attack", attacker=BLADE, attribute="swiftness", kind="art", art=1, target="pack_animal_2",
                                        label="Pincer launch"), lambda r: targets_of(r).get("pack_animal_2", {}).get("damage", 0) > 0 and ct.co("pack_animal_2")["hp"] > 0, what="launch hit")
    print("   launch result:", json.dumps(r)[:900])
    p2 = ct.co("pack_animal_2")
    check(p2["pos"] == [3, 2], f"launched into wall stays put: {p2['pos']}")
    check(p2["hp"] < hp_before - targets_of(r)["pack_animal_2"]["damage"] or "collision" in json.dumps(r).lower(),
          "wall collision should deal extra damage (remaining squares) or be reported")
    await ct("combat_end_turn", cid=BLADE, facing="E", expect_ok=True)

    # ---------------- AoE with an ally in the circle
    await to_turn(HERO)
    await stage([{"op": "move", "cid": "pack_animal_1", "to": [2, 3]}, {"op": "move", "cid": "pack_animal_2", "to": [2, 2]},
                 {"op": "set_hp", "cid": "pack_animal_1", "n": 5}, {"op": "set_hp", "cid": "pack_animal_2", "n": 5}, {"op": "set_hp", "cid": BLADE, "n": 14}])
    before = ct.snap()
    r = await retry_undo(ct, lambda: ct("combat_attack", attacker=HERO, attribute="might", kind="art", art=0, at=[1, 3], label="Ember Sweep",
                                        defender_attributes={BLADE: "stamina"}), lambda r: BLADE in targets_of(r) and len(r["targets"]) >= 2, what="AoE")
    tg = targets_of(r)
    check(BLADE in tg and "pack_animal_1" in tg and "pack_animal_2" in tg, f"AoE hits ally + both enemies: {list(tg)}")
    for cid, tr in tg.items():
        check(ct.co(cid)["hp"] == before[cid]["hp"] - tr.get("damage", 0), f"AoE hp consistency {cid}: {tr}")
    check(ct.co(HERO)["cooldowns"][0] == 6, f"circle art cooldown 6: {ct.co(HERO)['cooldowns']}")
    await ct("combat_end_turn", cid=HERO, facing="E")

    # ---------------- burning status expiring over rounds
    await to_turn(HERO)
    await stage([{"op": "move", "cid": "pack_animal_1", "to": [2, 3]}, {"op": "set_hp", "cid": "pack_animal_1", "n": 5}])
    # Seared Flame: unique_effect + topple(needs broken) + rear
    r = await retry_undo(ct, lambda: ct("combat_attack", attacker=HERO, attribute="willpower", kind="art", art=2, target="pack_animal_1",
                                        effect="burning_blade", label="Seared Flame"),
                         lambda r: targets_of(r).get("pack_animal_1", {}).get("damage", 0) > 0 and ct.co("pack_animal_1")["hp"] > 0, what="burn hit")
    st_ = [s for s in ct.co("pack_animal_1")["statuses"] if s["id"] == "burning"]
    check(len(st_) == 1, f"burning applied: {ct.co('pack_animal_1')['statuses']}")
    rem0 = st_[0]["remaining"] if st_ else 0
    await ct("combat_end_turn", cid=HERO, facing="E")
    seen = [rem0]
    for _ in range(14):
        if ct.co("pack_animal_1")["down"]:
            break
        s2 = [s for s in ct.co("pack_animal_1")["statuses"] if s["id"] == "burning"]
        seen.append(s2[0]["remaining"] if s2 else 0)
        if not s2:
            break
        a = ct.actor()
        if ct.co(a)["kind"] == "npc":
            await ct.auto_turn()
        else:
            await ct.end_turn(a)
    print("   burning remaining over time:", seen)
    check(ct.co("pack_animal_1")["down"] or seen[-1] == 0, "burning eventually expires")

    # ---------------- turn swap
    await to_turn(HERO)
    r = await ct("combat_swap_turn", cid=HERO)
    print("   swap:", r.get("ok"), r.get("errors") or r.get("summary"))
    if r.get("ok"):
        check(ct.actor() == BLADE, f"after swap partner acts: {ct.actor()}")
        await ct.end_turn(BLADE)
    # ---------------- special points building + L1 -> L2 (split) -> L3 under one-team rule
    await to_turn(HERO)
    tid = "t_kael-varrow"
    for c in list(ct.c["combatants"].values()):
        if c["side"] == "enemy" and c["down"]:
            await ct("combat_adjust", ops=[{"op": "revive", "cid": c["cid"], "hp": 6}])
    await stage([{"op": "move", "cid": "pack_animal_1", "to": [3, 3]}, {"op": "move", "cid": "pack_animal_2", "to": [3, 4]},
                 {"op": "move", "cid": "pack_animal_3", "to": [4, 4]}, {"op": "set_hp", "cid": "pack_animal_3", "n": 5},
                 {"op": "special_points", "team_id": tid, "value": 18}, {"op": "chain_level", "value": 0}])
    check(ct.c["special"]["points"][tid] == 18, "fiat special points")
    r = await ct("combat_special", attacker=HERO, level=2, ideas={HERO: "bravery", BLADE: "bravery"}, target="pack_animal_1", expect_ok=False)
    check(any("level" in e.lower() for e in r["errors"]), f"skipping level 1 error: {r['errors']}")
    r = await ct("combat_special", attacker=HERO, level=1, ideas={HERO: "bravery"}, target="pack_animal_1", effect="burning_blade",
                 label="Flare", expect_ok=True)
    check(ct.c["special"]["chain_level"] == 1, f"chain level 1: {ct.c['special']}")
    check(ct.c["special"]["points"][tid] == 18, f"one-team: L1 spends nothing: {ct.c['special']['points']}")
    await ct("combat_end_turn", cid=HERO, facing="E")
    await to_turn(HERO)
    await stage([{"op": "move", "cid": "pack_animal_1", "to": [3, 3]}, {"op": "move", "cid": "pack_animal_2", "to": [3, 4]},
                 {"op": "move", "cid": "pack_animal_3", "to": [2, 4]}])
    for c in ("pack_animal_1", "pack_animal_2", "pack_animal_3"):
        await ct("combat_adjust", ops=[{"op": "set_hp", "cid": c, "n": 5}] if not ct.co(c)["down"] else [{"op": "revive", "cid": c, "hp": 5}])
    await stage([])
    r = await ct("combat_special", attacker=HERO, level=2, ideas={HERO: "justice", BLADE: "justice"}, at=[3, 4], effect="blinding_eclipse", label="Double edge", expect_ok=True)
    print("   L2 result:", json.dumps(r)[:600])
    if ct.c.get("pending"):
        print("   pending:", ct.c["pending"])
        check(ct.c["pending"]["type"] == "special_split", "pending special_split")
        r2 = await ct("combat_move", cid=HERO, to=[1, 2], expect_ok=False)
        check(any("combat_special_assign" in e for e in r2["errors"]), f"pending error must name combat_special_assign: {r2['errors']}")
        check("combat_special_assign" in json.dumps(r), f"L2 result should say to call combat_special_assign: {json.dumps(r)[:300]}")
        p = ct.c["pending"]
        total = p.get("total", p.get("damage"))
        cands = p.get("targets") or p.get("candidates") or []
        cands = [x if isinstance(x, str) else x.get("cid") for x in cands]
        alloc = {}
        left = total or 0
        for i_, cid in enumerate(cands):
            give = left if i_ == len(cands) - 1 else min(1, left)
            alloc[cid] = give; left -= give
        r3 = await ct("combat_special_assign", allocations=alloc, expect_ok=True)
        check(ct.c.get("pending") is None, "pending cleared after assign")
    check(ct.c["special"]["chain_level"] == 2, f"chain level 2: {ct.c['special']}")
    await ct("combat_end_turn", cid=HERO, facing="E")
    await to_turn(HERO)
    await stage([{"op": "revive", "cid": "pack_animal_1", "hp": 5}] if ct.co("pack_animal_1")["down"] else [])
    r = await ct("combat_special", attacker=HERO, level=3, ideas={HERO: "bravery", BLADE: "compassion"}, at=[3, 4], effect="burning_blade", label="Everything", expect_ok=True)
    print("   L3 result:", json.dumps(r)[:500])
    if ct.c.get("pending"):
        p = ct.c["pending"]; cands = [x if isinstance(x, str) else x.get("cid") for x in (p.get("targets") or p.get("candidates") or [])]
        cands = [c for c in cands if ct.co(c)["side"] == "enemy"]
        await ct("combat_special_assign", allocations={cands[0]: p.get("total", p.get("damage"))}, expect_ok=True)
    check(ct.c["special"]["chain_level"] == 0, f"chain resets after L3: {ct.c['special']}")
    check(ct.c["special"]["points"][tid] == 0, f"L3 spends all 18 points (one-team): {ct.c['special']['points']}")
    await ct("combat_end_turn", cid=HERO, facing="E")

    # ---------------- Bearer to 0: life force sharing
    await to_turn("pack_animal_3")
    for c in ("pack_animal_1", "pack_animal_2", "pack_animal_3"):
        if ct.co(c)["down"]:
            await ct("combat_adjust", ops=[{"op": "revive", "cid": c, "hp": 5}])
    await ct.sync()
    for pc in (HERO, BLADE):
        if ct.co(pc)["down"]:
            await ct("combat_adjust", ops=[{"op": "revive", "cid": pc, "hp": 5}], expect_ok=True)
    await ct("combat_adjust", ops=[{"op": "set_hp", "cid": HERO, "n": 1}, {"op": "set_hp", "cid": BLADE, "n": 14},
                                   {"op": "move", "cid": "pack_animal_3", "to": [ct.co(HERO)["pos"][0] + 1, ct.co(HERO)["pos"][1]] if True else None}], expect_ok=None)
    r = await retry_undo(ct, lambda: ct("combat_npc_attack", attacker="pack_animal_3", targets=[HERO], level=4, defender_attributes={HERO: "might"}, label="crushing blow"),
                         lambda r: bool(ct.c.get("pending")), what="life_force pending")
    print("   life force result:", json.dumps(r)[:500])
    check(ct.c.get("pending") and ct.c["pending"]["type"] == "life_force", f"pending life_force: {ct.c.get('pending')}")
    check("combat_life_force" in json.dumps(r), f"result must name combat_life_force: {json.dumps(r)[:300]}")
    r2 = await ct("combat_end_turn", cid="pack_animal_3", expect_ok=False)
    check(r2.get("ok") is False and any("combat_life_force" in e for e in r2.get("errors", [])), f"pending error names tool: {r2}")
    r2 = await ct("combat_attack", attacker=BLADE, attribute="might", target="pack_animal_1", expect_ok=False)
    check(any("combat_life_force" in e for e in r2["errors"]), f"pending error names tool (attack): {r2['errors']}")
    bh = ct.co(BLADE)["hp"]
    r = await ct("combat_life_force", give=2, expect_ok=True)
    print("   life force resolved:", json.dumps(r)[:300])
    check(ct.co(HERO)["hp"] == 2, f"bearer restored to give=2: {ct.co(HERO)['hp']}")
    check(ct.co(BLADE)["hp"] < bh, f"blade paid HP: {bh} -> {ct.co(BLADE)['hp']}")
    check(ct.c.get("pending") is None, "life_force pending cleared")

    # ---------------- fiat ops
    await ct("combat_adjust", ops=[{"op": "damage", "cid": "cinder_captain", "n": 2}, {"op": "heal", "cid": "cinder_captain", "n": 1},
                                   {"op": "status_add", "cid": "cinder_captain", "id": "blinded", "remaining": 2},
                                   {"op": "status_remove", "cid": "cinder_captain", "id": "blinded"},
                                   {"op": "face", "cid": "cinder_captain", "dir": "W"}, {"op": "shift_order", "cid": "cinder_edge", "delta": 1},
                                   {"op": "cell", "x": 9, "y": 0, "type": "hazard", "label": "spill"},
                                   {"op": "add_combatant", "name": "Stray Pup", "card": dict(CARD, hp=2), "pos": [9, 7], "side": "neutral"}], reason="kitchen sink", expect_ok=True)
    check(ct.co("cinder_captain")["hp"] == 6, f"damage 2 heal 1 -> 6: {ct.co('cinder_captain')['hp']}")
    await ct("combat_adjust", ops=[{"op": "remove_combatant", "cid": "stray_pup"}], expect_ok=True)
    await ct("combat_adjust", ops=[{"op": "bogus"}], expect_ok=False)
    # ---------------- undo a combat step
    await ct.sync()
    snap0 = ct.snap()
    a = ct.actor()
    if ct.co(a)["kind"] == "npc":
        await ct("combat_end_turn", cid=a)
        await ct("undo", steps=1, expect_ok=True)
        snap1 = ct.snap()
        check(snap1["_order"] == snap0["_order"] and all(snap1[k] == snap0[k] for k in snap0 if not k.startswith("_")), "undo of end_turn restores state exactly")

    # ---------------- run to the end
    await ct.sync()
    saw_suggest = False
    for n in range(80):
        if not ct.living("enemy"):
            break
        a = ct.actor()
        me = ct.co(a)
        if n > 25 and me["side"] == "party":       # speed things up with fiat damage after a while
            for e in ct.living("enemy")[:1]:
                await ct("combat_adjust", ops=[{"op": "damage", "cid": e["cid"], "n": 3}])
        await ct.auto_turn()
    for _ in range(3):
        if ct.living("enemy"):
            for e in ct.living("enemy"):
                await ct("combat_adjust", ops=[{"op": "down", "cid": e["cid"]}])
    r = await ct("combat_state", expect_ok=True)
    check("suggest_end" in json.dumps(r) or not ct.living("enemy"), "all enemies down")
    print("   suggest_end present in combat_state:", "suggest_end" in json.dumps(r))
    r = await ct("combat_end", outcome="victory", summary="The yard is quiet.", expect_ok=True)
    st = await t("get_state", scope="summary", quiet=True)
    check(st.get("combat") is None and st["clock"]["combats"] >= 1, f"combat cleared: {st.get('clock')}")
    await ct.sync()
    check(all(c["hp"] == c["derived"]["max_hp"] for c in ct.chars.values()), "hp restored after combat_end")
    return ct


# ====================================================================== fuzz
BESTIARY = ["pack_animal", "elemental_ursine", "novice_bearer", "forgeling_blade", "blade_eater", "legendary_bearer", "titanic_blade", "rockbart"]
EFFECTS = ["burning_blade", "arts_seal", "blustering_gale", "freezing_force", "cradling_earth", "electrifying_burst", "blade_of_light",
           "shadow_manipulation", "invigorating_steam", "bitter_snowstorm", "counter_spike", "blinding_eclipse", "none", "bogus"]
ATTRS = ["might", "willpower", "calculation", "gut", "experience", "knowledge", "stamina", "empathy", "attunement", "swiftness", "improvisation", "passion"]


def rand_pos(rng, W, H):
    return [rng.randint(-1, W), rng.randint(-1, H)] if rng.random() < 0.25 else [rng.randrange(W), rng.randrange(H)]


async def fuzz_one(t, seed, steps=70):
    rng = random.Random(seed)
    ct = CT(t, rng, verbose=False)
    st = (await t("get_state", scope="summary", quiet=True))
    if st.get("combat"):
        await t("combat_end", outcome="other", quiet=True)
    for cid in (HERO, BLADE):
        await t("character_update", char_id=cid, patch={"arc_abilities": {"feeling_it": True, "reyn_time": True, "heronop": True}, "hp_delta": 0}, quiet=True)
    W, H = rng.randint(6, 12), rng.randint(5, 10)
    cells, taken = [], set()
    def cell():
        while True:
            p = (rng.randrange(W), rng.randrange(H))
            if p not in taken:
                taken.add(p); return p
    for _ in range(rng.randint(0, W * H // 8)):
        x, y = cell()
        cells.append({"x": x, "y": y, "type": rng.choice(["wall", "obstacle", "hazard", "difficult", "cover", "feature"])})
    # open squares for combatants
    free = [(x, y) for x in range(W) for y in range(H) if (x, y) not in taken]
    rng.shuffle(free)
    kp = free.pop(); bp = None
    for q in free:
        if max(abs(q[0] - kp[0]), abs(q[1] - kp[1])) <= 2:
            bp = q; free.remove(q); break
    if bp is None:
        return None
    combatants = [{"char_id": HERO, "pos": list(kp), "facing": rng.choice("NESW")}, {"char_id": BLADE, "pos": list(bp)}]
    n_enemy = rng.randint(1, 4)
    for i in range(n_enemy):
        if not free:
            break
        pos = free.pop()
        kind = rng.choice(BESTIARY + ["custom", "custom"])
        if kind == "custom":
            card = dict(CARD, hp=rng.randint(2, 12), range=rng.randint(1, 3), attack={"dis": 1, "normal": rng.randint(1, 4), "adv": 5})
            combatants.append({"name": f"Thug {i}", "card": card, "pos": list(pos)})
        elif kind in ("forgeling_blade", "titanic_blade", "blade_eater"):
            # needs a bearer: give it one
            if free:
                bpos = free.pop()
                combatants.append({"name": f"Bearer {i}", "card": dict(CARD), "pos": list(bpos)})
                combatants.append({"name": f"Blade {i}", "bestiary": kind, "bearer": f"Bearer {i}", "pos": list(pos)})
        else:
            combatants.append({"name": f"Beast {i}", "bestiary": kind, "pos": list(pos)})
    fi = [{"char_id": HERO, "attribute": rng.choice(ATTRS), "reason": "fuzz"}] if rng.random() < 0.4 else []
    r = await ct("combat_start", name=f"Fuzz {seed}", map={"width": W, "height": H, "cells": cells}, combatants=combatants, feeling_it=fi)
    if not r.get("ok"):
        check(any(isinstance(e, str) and e for e in r.get("errors", [])), f"fuzz {seed}: combat_start failed without message: {r}")
        return {"started": False, "errors": r.get("errors")}
    await ct.sync()
    stats = {"started": True, "steps": 0, "ok": 0, "err": 0}
    cids = list(ct.c["combatants"])
    for step in range(steps):
        if not ct.c or not ct.living("enemy") or not [c for c in ct.living("party")]:
            break
        stats["steps"] += 1
        roll = rng.random()
        pend = ct.c.get("pending")
        if pend and rng.random() < 0.7:
            await ct.resolve_pending(decline_p=0.3)
            continue
        if roll < 0.55:
            await ct.auto_turn()
            continue
        tool = rng.choice(["move", "attack", "npc_attack", "special", "action", "swap", "delay", "adjust", "undo", "state", "end_turn", "assign", "life", "special_assign_bad"])
        me = ct.actor()
        any_cid = rng.choice(cids + ["ghost"])
        a = {}
        if tool == "move":
            r = await ct("combat_move", cid=rng.choice([me, me, any_cid]), to=rand_pos(rng, W, H), quiet=True, **({"forced": True} if rng.random() < 0.1 else {}))
        elif tool == "attack":
            pcs = [c["cid"] for c in ct.living("party")]
            tgt = rng.choice(cids)
            args = dict(attacker=rng.choice([me, rng.choice(pcs)]), attribute=rng.choice(ATTRS + ["bogus"]), kind=rng.choice(["basic", "art", "art", "weird"]),
                        art=rng.choice([None, 0, 1, 2, 3, -1]), target=rng.choice([tgt, None]), label="fuzz",
                        defender_attributes={c: rng.choice(ATTRS) for c in pcs})
            if rng.random() < 0.4:
                args["at"] = rand_pos(rng, W, H)
            if rng.random() < 0.3:
                args["effect"] = rng.choice(EFFECTS)
            if rng.random() < 0.2:
                args["direction"] = rng.choice(["N", "E", "S", "W", "X"])
            if rng.random() < 0.1:
                args["force"] = True
            r = await ct("combat_attack", quiet=True, **args)
        elif tool == "npc_attack":
            npcs = [c["cid"] for c in ct.living("enemy")]
            pcs = [c["cid"] for c in ct.living("party")]
            args = dict(attacker=rng.choice([me, rng.choice(npcs)]), targets=rng.sample(pcs, min(len(pcs), rng.randint(0, 2))) or None,
                        level=rng.choice(["normal", "adv", "dis", 0, 5, "bogus"]), defender_attributes={c: rng.choice(ATTRS) for c in pcs},
                        tags=rng.sample(["break", "topple", "launch", "stagger", "rush", "circle", "line", "range", "nonsense"], rng.randint(0, 3)))
            if rng.random() < 0.3:
                args["effect"] = rng.choice(EFFECTS)
            if "circle" in args["tags"] or rng.random() < 0.2:
                args["at"] = rand_pos(rng, W, H)
            if rng.random() < 0.2:
                args["ignore_range"] = True
            r = await ct("combat_npc_attack", quiet=True, **args)
        elif tool == "special":
            lvl = rng.choice([0, 1, 2, 3, 4])
            if rng.random() < 0.5:
                await ct("combat_adjust", ops=[{"op": "special_points", "team_id": "t_kael-varrow", "value": rng.choice([0, 6, 12, 18])}], quiet=True)
            args = dict(attacker=rng.choice([HERO, BLADE, me]), level=lvl, ideas={HERO: rng.choice(["bravery", "truth", "compassion", "justice", "bogus"]),
                        BLADE: rng.choice(["bravery", "truth", "compassion", "justice"])}, label="fuzz")
            if rng.random() < 0.6:
                args["target"] = rng.choice(cids)
            else:
                args["at"] = rand_pos(rng, W, H)
            if rng.random() < 0.3:
                args["effect"] = rng.choice(EFFECTS)
            if rng.random() < 0.1:
                args["free_burst"] = True
            r = await ct("combat_special", quiet=True, **args)
        elif tool == "action":
            r = await ct("combat_action", cid=rng.choice([me, any_cid]), label="fuzz", attribute=rng.choice(ATTRS + [None]), check=rng.randint(0, 3),
                         kind=rng.choice(["other", "help_up", "defend", "heal", "bogus"]), target=rng.choice([None, any_cid]), art=rng.choice([None, 0, 1, 2]), quiet=True)
        elif tool == "swap":
            r = await ct("combat_swap_turn", cid=rng.choice([me, any_cid]), quiet=True)
        elif tool == "delay":
            r = await ct("combat_delay", cid=rng.choice([me, any_cid]), places=rng.randint(-1, 4), quiet=True)
        elif tool == "adjust":
            c_ = rng.choice([x for x in cids if x in ct.c["combatants"]] or [HERO])
            op = rng.choice(["damage", "heal", "set_hp", "status_add", "status_remove", "move", "face", "shift_order", "special_points", "cooldown", "cell", "chain_level", "down", "revive", "add_combatant", "remove_nonpc", "bogus"])
            ops = {"damage": {"op": "damage", "cid": c_, "n": rng.randint(-1, 6)}, "heal": {"op": "heal", "cid": c_, "n": rng.randint(0, 6)},
                   "set_hp": {"op": "set_hp", "cid": c_, "n": rng.randint(-2, 20)},
                   "status_add": {"op": "status_add", "cid": c_, "id": rng.choice(["burning", "frozen", "broken", "toppled", "blinded", "arts_seal", "snowstorm", "mystery"]), "remaining": rng.randint(0, 9)},
                   "status_remove": {"op": "status_remove", "cid": c_, "id": "burning"}, "move": {"op": "move", "cid": c_, "to": rand_pos(rng, W, H)},
                   "face": {"op": "face", "cid": c_, "dir": rng.choice("NESWX")}, "shift_order": {"op": "shift_order", "cid": c_, "delta": rng.randint(-4, 4)},
                   "special_points": {"op": "special_points", "team_id": rng.choice(["t_kael-varrow", "nope"]), "delta": rng.randint(-20, 20)},
                   "cooldown": {"op": "cooldown", "cid": c_, "art": rng.randint(0, 3), "value": rng.randint(-2, 9)},
                   "cell": {"op": "cell", "x": rng.randrange(W), "y": rng.randrange(H), "type": rng.choice(["hazard", "difficult", None, "feature"])},
                   "chain_level": {"op": "chain_level", "value": rng.randint(0, 3)}, "down": {"op": "down", "cid": c_},
                   "revive": {"op": "revive", "cid": c_, "hp": rng.randint(0, 5)},
                   "add_combatant": {"op": "add_combatant", "name": f"Extra{step}", "card": dict(CARD, hp=3), "pos": rand_pos(rng, W, H), "side": "enemy"},
                   "remove_nonpc": {"op": "remove_combatant", "cid": rng.choice([x for x in cids if x not in (HERO, BLADE)] or ["ghost"])},
                   "bogus": {"op": rng.choice(["fly", "", None])}}[op]
            r = await ct("combat_adjust", ops=[ops], quiet=True)
            if r.get("ok") and op == "add_combatant":
                cids = list(ct.c["combatants"])
        elif tool == "undo":
            r = await ct("undo", steps=1, quiet=True)
            if ct.c is None:
                break
        elif tool == "state":
            r = await ct("combat_state", cid=rng.choice([None, "current", any_cid]), quiet=True)
        elif tool == "end_turn":
            r = await ct("combat_end_turn", cid=rng.choice([me, any_cid]), facing=rng.choice(list("NESWX") + [None]),
                         blade_pos=rand_pos(rng, W, H) if rng.random() < 0.2 else None, quiet=True)
        elif tool == "assign":
            r = await ct("combat_special_assign", allocations={rng.choice(cids): rng.randint(0, 5)}, quiet=True)
        elif tool == "life":
            r = await ct("combat_life_force", give=rng.choice([None, 0, 1, 3]), decline=rng.random() < 0.2, quiet=True)
        else:
            r = await ct("combat_special_assign", allocations={}, quiet=True)
        stats["ok" if r.get("ok") else "err"] += 1
        if not ct.c:
            break
    await ct.sync()
    if ct.c:
        for pc in (HERO, BLADE):
            pass
        r = await ct("combat_end", outcome=rng.choice(["victory", "defeat", "fled"]), restore_hp=rng.random() < 0.5, quiet=True)
        check(r.get("ok"), f"fuzz {seed}: combat_end failed: {r}")
        await ct.sync()
        for cid, c in ct.chars.items():
            check(0 <= c["hp"] <= c["derived"]["max_hp"], f"fuzz {seed}: after combat_end {cid} hp {c['hp']}/{c['derived']['max_hp']}")
        # heal whoever is damaged / dead flag clean for next round
        for cid in (HERO, BLADE):
            await t("character_update", char_id=cid, patch={"hp": ct.chars[cid]["derived"]["max_hp"]}, quiet=True)
    return stats


async def fuzz(t, n=30, seed0=1000):
    print(f"\n===== FUZZ: {n} random combats =====")
    tot = {"combats": 0, "steps": 0, "ok": 0, "err": 0, "start_failed": 0}
    for i in range(n):
        s = await fuzz_one(t, seed0 + i)
        if not s:
            continue
        if not s["started"]:
            tot["start_failed"] += 1
            continue
        tot["combats"] += 1
        for k in ("steps", "ok", "err"):
            tot[k] += s[k]
        if (i + 1) % 10 == 0:
            print("  ..", i + 1, tot)
    print("  FUZZ TOTAL", tot)
    return tot
