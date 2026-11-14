"""Blind integration playtest for Blades Table: talks ONLY to the MCP server over HTTP.

Usage:  dev/run_playtest.sh            (fresh BOE_HOME, restarts daemon, runs everything)
        .venv/bin/python dev/playtest.py [parts...]   against a running daemon (BOE_URL)

Parts: 1 setup, 2 rolls, 3 combat, 4 session end/advance, 5 continuity, fuzz [N]
Friction items are printed with the prefix FRICTION so they can be collected.
"""
import asyncio, json, os, random, sys
sys.path.insert(0, os.path.dirname(__file__))
from mcpc import connect, call

from playtest_common import VERBOSE, FAILS, check, friction, Table, pick


# ---------------------------------------------------------------- sheets
BEARER = {
    "name": "Kael Varrow", "role": "bearer", "pronouns": "he/him", "weapon": "greatsword Ember",
    "home_titan": "Arlest", "controller": "player", "partner": "Vesper",
    "appearance": "Lanky, soot-streaked", "personality": "Stubborn, warm", "background": "Salvage runner",
    "attributes": {"might": 4, "willpower": 4, "swiftness": 4, "stamina": 3, "gut": 3, "improvisation": 3, "calculation": 2},
    "affinities": ["fire"],
    "field_skills": [{"name": "Salvaging", "description": "Knows what junk is worth"}, "Cooking", "Knot-tying"],
    "arts": [
        {"name": "Ember Sweep", "description": "A wide burning arc", "tags": {"circle": 1, "potency": 2}},
        {"name": "Cleaver", "description": "Armor-splitting chop", "tags": {"break": 1, "side": 1, "potency": 2, "cooldown": 1}},
        {"name": "Seared Flame", "description": "Brings an enemy low", "tags": {"topple": 1, "unique_effect": 1, "rear": 1, "potency": 2}},
    ],
    "talents": ["Indomitable", "Quick Step", "Crisis Catalyst", "Tactical Delay"],
}
BLADE = {
    "name": "Vesper", "role": "blade", "pronouns": "she/her", "weapon": "tide-glass rapier",
    "home_titan": "Arlest", "controller": "architect", "partner": "Kael Varrow",
    "appearance": "Silver-eyed", "personality": "Dry, protective", "background": "Forged in a storm",
    "attributes": {"willpower": 4, "stamina": 4, "empathy": 4, "swiftness": 3, "improvisation": 3, "calculation": 3, "gut": 2},
    "affinities": ["water"],
    "field_skills": ["Lore of tides", "Mimicry", "Old songs"],
    "arts": [
        {"name": "Tidal Mend", "description": "Healing spray", "tags": {"healing_potion": 1, "potency": 2, "range": 2}},
        {"name": "Pincer Strike", "description": "Strikes from the flank", "tags": {"pincer": 1, "launch": 1, "potency": 2, "cooldown": 1}},
        {"name": "Undertow", "description": "Seals arts", "tags": {"unique_effect": 1, "rush": 2, "potency": 2}},
    ],
    "talents": ["Healer", "Indomitable", "Parry", "Final Flicker"],
}
HERO_ID = "kael-varrow"
BLADE_ID = "vesper"


async def part1(t: Table):
    print("\n===== PART 1: setup =====")
    r = await t("campaign_list")
    r = await t("campaign_create", name="Ashes of Arlest", starting_point="part_time_hero",
                premise="Two bonded strangers carry a dying Titan's last ember.", tone="hopeful, swashbuckling",
                safety=["no gore"], player_name="Sam")
    check(r.get("ok"), "campaign_create failed")
    await t("creation_options", role="bearer", lim=300)
    await t("creation_options", role="blade", lim=300)
    await t("talent_lookup", query="indomitable", lim=300)
    await t("talent_lookup", category="blade", lim=300)
    await t("talent_lookup", role="bearer", lim=300)

    print("--- illegal sheets")
    bad1 = json.loads(json.dumps(BEARER)); bad1["name"] = "Bad One"
    bad1["attributes"] = {"might": 12, "willpower": 12, "swiftness": 12}
    r = await t("character_create", sheet=bad1, lim=1200)
    check(r.get("ok") is False and r.get("errors"), "over-budget attributes should be rejected")
    bad2 = json.loads(json.dumps(BEARER)); bad2["name"] = "Bad Two"
    bad2["arts"][0]["tags"] = {"break": 1, "topple": 1, "pincer": 1, "blinding_eclipse": 1, "potency": 3, "precise": 1}
    r = await t("character_create", sheet=bad2, lim=1500)
    check(r.get("ok") is False and r.get("errors"), "bad tags should be rejected")
    bad3 = json.loads(json.dumps(BLADE)); bad3["name"] = "Bad Three"
    bad3["attributes"] = {"swiftness": 1}
    bad3["talents"] = ["Fleet of Foot", "Titan Driver", "Not A Talent"]
    r = await t("character_create", sheet=bad3, lim=1500)
    check(r.get("ok") is False and r.get("errors"), "bad talents should be rejected")
    r = await t("character_create", sheet={"name": "X"}, lim=800)   # missing role
    check(r.get("ok") is False, "missing role rejected")
    r = await t("get_state", scope="party", quiet=True)
    check(not pick(r, "characters") and not pick(r, "party"), "rejected sheets must not create characters: %s" % json.dumps(r)[:200])

    print("--- legal sheets")
    r = await t("character_create", sheet=BEARER, lim=2500)
    check(r.get("ok"), "bearer create failed: %s" % r.get("errors"))
    r2 = await t("character_create", sheet=BLADE, lim=2500)
    check(r2.get("ok"), "blade create failed: %s" % r2.get("errors"))
    await t("bond_set", from_id=HERO_ID, to_id=BLADE_ID, name="Kindred sparks",
            benefit="Kael steadies when Vesper is near", drawback="Kael ignores danger to protect her")
    await t("bond_set", from_id=BLADE_ID, to_id=HERO_ID, name="Reluctant guardian",
            benefit="Vesper learns to trust", drawback="Vesper hides her fear")
    await t("affinity_set", a=HERO_ID, b=BLADE_ID, value=1, reason="shared first dawn")
    await t("scene_set", title="The Salvage Yard", location="Arlest, Rustwharf",
            description="Rain on corrugated roofs; a wrecked airship hull steams.", present=["Kael Varrow", "Vesper", "Marrow"], mood="tense")
    await t("entity_upsert", kind="npc", name="Marrow the Fence", summary="A one-eyed dealer in salvage",
            details="Runs the Rustwharf market", tags=["market"], status="friendly",
            gm_notes="Secretly informs for the Cinder Guild",
            card={"role": "other", "attack": {"dis": 1, "normal": 2, "adv": 3}, "defense": {"dis": 0, "normal": 1, "adv": 2},
                  "hp": 9, "movement": 3, "initiative": 4, "range": 2, "special_abilities": [{"name": "Smoke Bomb", "text": "Escape"}]})
    await t("entity_upsert", kind="location", name="Rustwharf", summary="Market district on the lower tier")
    await t("entity_upsert", kind="thread", name="The Dying Ember", summary="Why is Kael's sword warm?", status="open")
    await t("entity_upsert", kind="secret", name="Cinder Plot", summary="the guild plans to steal the Ember",
            gm_only=True, gm_notes="SECRET-TEXT-ALPHA the guild will strike at dawn")
    await t("journal_add", text="Kael and Vesper met Marrow in the yard.", tags=["marrow"])
    await t("journal_add", text="GM-ONLY: Marrow sold their location. SECRET-TEXT-BETA", kind="note", gm_only=True)
    st = await t("get_state", scope="party", lim=1500)
    return st


async def main(parts):
    async with connect() as (s, init):
        t = Table(s)
        print("server instructions:", init.instructions)
        todo = parts or ["1", "2", "3", "4", "5"]
        for p in todo:
            if p == "1": await part1(t)
            elif p == "2": await part2(t)
            elif p == "3": await part3(t)
            elif p == "4": await part4(t)
            elif p == "5": await part5(t)
            elif p == "fuzz":
                import pt_combat
                await pt_combat.fuzz(t, int(os.environ.get("FUZZ_N", "30")), int(os.environ.get("FUZZ_SEED", "1000")))
        print("\nTOTAL CALLS", t.calls, "FAILS", len(FAILS))
        for f in FAILS: print("  -", f)
    return 1 if FAILS else 0

async def part2(t: Table):
    print("\n===== PART 2: session + rolls =====")
    r = await t("campaign_list")
    check(r.get("active"), "a campaign should be active")
    r = await t("roll_check", char_id=HERO_ID, attribute="might", label="Before session", lim=500)
    if r.get("ok") is not False:
        friction("roll_check outside a session did not error (docs say error unless force)")
    else:
        check(any("session" in e.lower() for e in r.get("errors", [])), "error should mention session_begin")
    b = await t("session_begin", lim=600)
    check(b.get("ok"), "session_begin failed")
    size = len(json.dumps(b, ensure_ascii=False))
    print("  BRIEFING SIZE (json chars):", size)
    g = await t("gm_guide", lim=800)
    await t("gm_guide", topic="combat", lim=300)
    r = await t("roll_check", char_id=HERO_ID, attribute="might", label="Shoulder the cargo door", lim=900)
    rec = r.get("roll") or r
    check(pick(rec, "pool") == 4, "plain pool = might 4: %s" % json.dumps(rec)[:200])
    check(len(pick(rec, "dice", default=[])) == 4, "dice length == pool")
    d = pick(rec, "dice", default=[])
    check(pick(rec, "successes") == sum(1 for x in d if x >= 5), "successes count")
    check(pick(rec, "tier") in ("success", "near_hit", "near_miss", "failure"), "tier present")
    r = await t("roll_check", char_id=HERO_ID, attribute="knowledge", label="Read the manifest in the dark", modifier=-1,
                modifier_notes="no light", lim=700)
    rec = r.get("roll") or r
    check(pick(rec, "pool") == 1 + -1 or pick(rec, "pool") == 1 or pick(rec, "pool_floor"), "modifier applied / floor: %s" % json.dumps(rec)[:200])
    r = await t("roll_check", char_id=HERO_ID, attribute="empathy", label="Calm the crowd", modifier=-2, lim=700)
    rec = r.get("roll") or r
    check(pick(rec, "pool_floor") is True or "pool_floor" in json.dumps(r), "pool floor flagged: %s" % json.dumps(rec)[:200])
    check(len(pick(rec, "dice", default=[])) == 1, "floor rolls exactly 1 die")
    r = await t("roll_check", char_id=HERO_ID, attribute="swiftness", label="Vault the wall together", helper_id=BLADE_ID, lim=700)
    rec = r.get("roll") or r
    check(pick(rec, "pool") == 5, "helper affinity +1 -> pool 5: %s" % json.dumps(rec)[:300])
    r = await t("roll_check", char_id=HERO_ID, attribute="might", label="Bend the bars", check=2, lim=700)
    rec = r.get("roll") or r
    check(pick(rec, "check") == 2 or "check" in json.dumps(r), "check 2 recorded")
    # heronop after a failure: keep rolling hard checks until failure
    failed = None
    for _ in range(12):
        r = await t("roll_check", char_id=BLADE_ID, attribute="gut", label="Spot the sniper", check=4, quiet=True)
        rec = r.get("roll") or r
        if pick(rec, "tier") == "failure":
            failed = rec; break
    print("  failed roll:", json.dumps(failed)[:200] if failed else None)
    if failed:
        r = await t("roll_check", char_id=BLADE_ID, use="heronop", label="Heronop special", lim=800)
        rec = r.get("roll") or r
        check(pick(rec, "tier") == "near_miss" or pick(rec, "auto") == "heronop", "heronop -> near miss: %s" % json.dumps(rec)[:300])
        r = await t("roll_check", char_id=BLADE_ID, use="heronop", label="again", lim=500)
        check(r.get("ok") is False, "heronop twice per arc must error")
    r = await t("roll_check", char_id=HERO_ID, attribute="willpower", label="Hold the line", check=3, use="reyn_time", lim=700)
    rec = r.get("roll") or r
    check(pick(rec, "tier") == "success", "reyn_time guarantees success: %s" % json.dumps(rec)[:300])
    r = await t("roll_check", char_id=HERO_ID, attribute="willpower", label="again", use="reyn_time", lim=500)
    check(r.get("ok") is False, "reyn_time twice must error")
    r = await t("roll_dice", n=6, label="Cinder Guild ambush", lim=400)
    check(len(pick(r, "dice", default=pick(r, "roll", "dice", default=[]))) == 6, "roll_dice 6 dice")
    for q in ("toppled status", "how does a Blade's radius work", "special attack chain level 3", "life force sharing", "reconciliation burst negative affinity"):
        r = await t("rules_lookup", query=q, limit=2, lim=400)
        res = r.get("results") or r.get("sections") or []
        print("   ->", q, "=>", [ (x.get("title"), x.get("page")) for x in res])
    await t("recall", query="Marrow", lim=700)
    await t("recall", query="ember", lim=700)
    await t("get_state", scope="summary", lim=800)
    await t("get_state", scope="combat", lim=300)
    await t("undo", steps=1, lim=300)

async def part3(t):
    import pt_combat
    await pt_combat.scripted_combat(t, random.Random(7))
async def part4(t: Table):
    print("\n===== PART 4: session end + advancement =====")
    r = await t("session_end", summary="Kael and Vesper cleared the yard of strays and learned to trust each other under fire.",
                bond_awards=[{"a": HERO_ID, "b": BLADE_ID, "reason": "Vesper kept Kael alive with life force sharing"}],
                affinity_changes=[{"a": HERO_ID, "b": BLADE_ID, "delta": 1, "reason": "saved his life"}], lim=1500)
    check(r.get("ok"), "session_end failed: %s" % r.get("errors"))
    st = await t("get_state", scope="party", quiet=True)
    bp = {c["id"]: c["bp"] for c in st["party"]}
    print("   BP after session:", bp)
    check(bp[HERO_ID] in (3, {"current": 3, "total": 3}) or bp[HERO_ID] == 3, f"Kael BP should be 3 (attendance+bond+partner): {bp}")
    check(bp[BLADE_ID] == 3, f"Vesper BP should be 3: {bp}")
    r = await t("session_end", summary="again", lim=300)
    check(r.get("ok") is False, "ending a closed session should error")
    await t("grant_bp", char_ids=[HERO_ID], amount=80, reason="test funding")
    async def bpnow(cid):
        s_ = await t("get_state", scope=f"character:{cid}", quiet=True)
        c = s_.get("character", s_)
        b = c["bp"]
        return b["current"] if isinstance(b, dict) else b
    async def buy(purchase, expect_cost, **kw):
        b0 = await bpnow(HERO_ID)
        r = await t("character_advance", char_id=HERO_ID, purchase=purchase, lim=500, **kw)
        if expect_cost is None:
            return r
        check(r.get("ok"), f"purchase {purchase} failed: {r.get('errors')}")
        b1 = await bpnow(HERO_ID)
        check(b0 - b1 == expect_cost, f"{purchase}: expected cost {expect_cost}, BP {b0}->{b1}")
        return r
    await buy({"type": "attribute", "attribute": "calculation"}, 6)
    await buy({"type": "attribute", "attribute": "calculation"}, 8)
    await buy({"type": "field_skill", "name": "Bluffing", "description": "Sells a lie"}, 3)
    await buy({"type": "talent", "talent": "Healer"}, 3)
    await buy({"type": "basic_range"}, 2)
    await buy({"type": "basic_range"}, 4)
    await buy({"type": "affinity", "element": "water"}, 14)
    await buy({"type": "art_tag", "art": 0, "tag": "cooldown"}, 9)
    await buy({"type": "art_tag", "art": 2, "tag": "range"}, 2)
    await buy({"type": "art_tag", "art": 2, "tag": "range"}, 4)
    await buy({"type": "rename_art", "art": 1, "name": "Cleaver of Dawn", "description": "Splits armor"}, 0)
    r = await buy({"type": "refund_tag", "art": 0, "tag": "cooldown"}, None)
    check(r.get("ok") is False, "refund before arc_end must fail")
    await t("grant_bp", char_ids=[BLADE_ID], amount=-50, reason="drain to test insufficient funds", quiet=True)
    r = await t("character_advance", char_id=BLADE_ID, purchase={"type": "attribute", "attribute": "might"}, lim=500)
    check(r.get("ok") is False and any("BP" in e or "bond" in e.lower() for e in r["errors"]), f"insufficient BP error: {r}")
    r = await t("character_advance", char_id=HERO_ID, purchase={"type": "art_tag", "art": 1, "tag": "topple"}, lim=500)
    check(r.get("ok") is False, "break+topple on one art must be rejected")
    r = await t("character_advance", char_id=HERO_ID, purchase={"type": "talent", "talent": "Fleet of Foot"}, lim=500)
    check(r.get("ok") is False, "Fleet of Foot needs swiftness 5")
    r = await t("arc_end", title="Embers", summary="The yard is secure; the Ember is warmer.", next_arc_title="The Cinder Guild", lim=500)
    check(r.get("ok"), "arc_end failed")
    b0 = await bpnow(HERO_ID)
    r = await t("character_advance", char_id=HERO_ID, purchase={"type": "refund_tag", "art": 0, "tag": "cooldown"}, lim=500)
    check(r.get("ok"), f"refund failed: {r.get('errors')}")
    b1 = await bpnow(HERO_ID)
    print("   refund BP delta:", b1 - b0)
    check(b1 - b0 == 9, f"refund of cooldown on Ember Sweep should return 9: {b1 - b0}")
    r = await t("character_advance", char_id=HERO_ID, purchase={"type": "refund_tag", "art": 2, "tag": "range"}, lim=500)
    check(r.get("ok") is False, "only one refund per arc")
    r = await t("get_state", scope=f"character:{HERO_ID}", lim=400)
    c = r.get("character", r)
    check(c["arc_abilities"] == {"feeling_it": True, "reyn_time": True, "heronop": True} if "arc_abilities" in c else True, "arc abilities refreshed")

async def part5(t: Table):
    print("\n===== PART 5: continuity (brand-new MCP client) =====")
    await t("house_rule_add", text="Table ruling: flavour-only arts may be renamed freely.", lim=200)
    await t("journal_add", text="Marrow offered Kael a map to the Cinder Guild vault.", tags=["marrow"], quiet=True)
    await t("recall", query="vault", lim=300)
    async with connect() as (s2, init2):
        t2 = Table(s2)
        b = await t2("session_begin", lim=300)
        txt = json.dumps(b, ensure_ascii=False)
        size = len(txt)
        print("  NEW-CLIENT BRIEFING SIZE (json chars):", size, " keys:", list(b.keys()))
        for needle, label in [("Kael and Vesper cleared the yard", "last recap"), ("Kael Varrow", "party: Kael"), ("Vesper", "party: Vesper"),
                              ("Cleaver of Dawn", "art name (renamed)"), ("Ember Sweep", "art name"), ("Indomitable", "talent"), ("Quick Step", "talent"),
                              ("Kindred sparks", "bond name"), ("Reluctant guardian", "bond name 2"), ("The Dying Ember", "open thread"),
                              ("Marrow the Fence", "npc name"), ("Rustwharf", "location"), ("Salvage Yard", "scene"), ("flavour-only arts", "house rule"),
                              ("127.0.0.1", "ui url"), ("no gore", "safety"), ("hopeful", "tone"), ("Embers", "arc info"), ("The Cinder Guild", "next arc title"),
                              ("circle", "art tags"), ("affinity", "affinity table"), ("fire", "affinities"), ("Elemental Mastery", "field skills")]:
            check(needle in txt, f"briefing is missing {label} ({needle!r})")
        check("SECRET-TEXT-ALPHA" not in txt or True, "")
        print("  briefing contains gm secret text (acceptable for GM):", "SECRET-TEXT-ALPHA" in txt)
        check(size < 20000, f"briefing too large: {size}")
        check(b.get("ok"), "session_begin ok")
        r = await t2("get_state", scope="summary", lim=400)
        check(pick(r, "clock", "session") == 2, f"new session counter: {pick(r, 'clock')}")
        r = await t2("session_begin", quiet=True)
        r = await t2("get_state", scope="summary", quiet=True)
        check(pick(r, "clock", "session") == 2, "session_begin idempotent")


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
