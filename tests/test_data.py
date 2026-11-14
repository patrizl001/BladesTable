"""Validation of the bundled rulebook data (boe/data/*.json) extracted from the Blades of Ether PDF."""
import json
import re
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "boe" / "data"

ATTRS = {"might", "willpower", "calculation", "gut", "experience", "knowledge", "stamina", "empathy",
         "attunement", "swiftness", "improvisation", "passion"}
ELEMENTS = {"fire", "water", "wind", "ice", "earth", "electricity", "light", "dark"}
TAG_IDS = {"break", "topple", "launch", "stagger", "rush", "unique_effect"}
ARCHETYPES = {"untouched": "bearer", "telethial": "bearer", "artificial_core": "blade", "flesh_eater": "blade",
              "dying_devotion": "pair", "body_core_soul": "pair"}
REQUIRED_TALENT_IDS = """indomitable fortified steel_flesh living_amalgam first_strike quick_step fleet_of_foot
swift_slide radius_master secondary_accelerator prime_position crisis_catalyst desperate_defense dirty_fighter
protective_aegis final_flicker expeditionist building_through_conflict healer elite_healer master_healer
tactical_delay artificial_core flesh_eater untouched telethial dying_devotion body_core_soul""".split()
# printed page -> number of talents on that page (verified against the PDF page by page)
TALENTS_PER_PAGE = {40: 6, 41: 13, 42: 9, 43: 5, 44: 15, 45: 13, 46: 8, 47: 10, 48: 8, 49: 7, 50: 6, 51: 7,
                    52: 4, 53: 5, 55: 4, 56: 4, 58: 1, 59: 4}


def load(name):
    with open(DATA / name, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def talents():
    return load("talents.json")["talents"]


@pytest.fixture(scope="module")
def tmap(talents):
    return {t["id"]: t for t in talents}


@pytest.fixture(scope="module")
def sections():
    return load("rules_sections.json")["sections"]


@pytest.fixture(scope="module")
def bestiary():
    return load("bestiary.json")["enemies"]


@pytest.fixture(scope="module")
def examples():
    return load("examples.json")


# ------------------------------------------------------------------------------------------------ talents
def test_talents_load_and_count(talents):
    assert isinstance(talents, list)
    assert len(talents) == sum(TALENTS_PER_PAGE.values()) == 129


def test_talents_per_page(talents):
    counts = {}
    for t in talents:
        counts[t["page"]] = counts.get(t["page"], 0) + 1
    assert counts == TALENTS_PER_PAGE


KEYS = {"id", "name", "rank", "rank_min", "rank_max", "category", "kind", "role", "requires", "creation_only",
        "excludes", "per", "repeatable", "text", "page"}


def test_talent_schema(talents):
    for t in talents:
        assert set(t) == KEYS, t["id"]
        assert re.fullmatch(r"[a-z][a-z0-9_]*", t["id"]), t["id"]
        assert t["name"] and t["name"] == t["name"].strip()
        if t["rank"] is None:
            assert isinstance(t["rank_min"], int) and isinstance(t["rank_max"], int)
            assert 1 <= t["rank_min"] < t["rank_max"]
        else:
            assert isinstance(t["rank"], int) and 1 <= t["rank"] <= 10
            assert t["rank_min"] is None and t["rank_max"] is None
        assert t["category"] in {"universal", "bearer", "blade", "pair", "archetype", "archetype_talent"}
        assert t["kind"] in {"general", "combat"}
        assert t["role"] in {"any", "bearer", "blade", "pair"}
        req = t["requires"]
        assert set(req) == {"attributes", "talents", "archetype"}
        assert set(req["attributes"]) <= ATTRS
        assert all(isinstance(v, int) and 1 <= v <= 12 for v in req["attributes"].values())
        assert isinstance(req["talents"], list)
        assert req["archetype"] is None or req["archetype"] in ARCHETYPES
        assert isinstance(t["creation_only"], bool) and isinstance(t["repeatable"], bool)
        assert isinstance(t["excludes"], list)
        assert t["per"] in {None, "arc", "session", "combat", "once"}
        assert isinstance(t["page"], int) and 40 <= t["page"] <= 59
        assert len(t["text"]) >= 15
        assert "  " not in t["text"] and "\n" not in t["text"]
        assert "(Rank" not in t["text"]


def test_talent_unique_ids(talents):
    ids = [t["id"] for t in talents]
    assert len(ids) == len(set(ids))
    names = [t["name"] for t in talents]
    assert len(names) == len(set(names))


def test_required_talent_ids(tmap):
    for tid in REQUIRED_TALENT_IDS:
        assert tid in tmap, tid


def test_talent_references(talents, tmap):
    for t in talents:
        for ref in t["requires"]["talents"] + t["excludes"]:
            assert ref in tmap, (t["id"], ref)
        assert t["id"] not in t["excludes"]


def test_archetype_structure(talents, tmap):
    for aid, role in ARCHETYPES.items():
        a = tmap[aid]
        assert a["category"] == "archetype" and a["rank"] == 1 and a["role"] == role
        assert a["requires"]["archetype"] is None
    subs = [t for t in talents if t["category"] == "archetype_talent"]
    assert {t["requires"]["archetype"] for t in subs} == {"untouched", "telethial", "artificial_core",
                                                          "flesh_eater", "body_core_soul"}
    for t in subs:
        assert t["role"] == ARCHETYPES[t["requires"]["archetype"]]
    for t in talents:
        if t["category"] != "archetype_talent":
            assert t["requires"]["archetype"] is None
    assert {t["id"] for t in subs if t["requires"]["archetype"] == "untouched"} == {
        "ether_filter", "etheric_reflector", "negative_presence"}
    assert {t["id"] for t in subs if t["requires"]["archetype"] == "telethial"} == {
        "drakos_wings", "soul_read", "disciples_control", "endbringers_power"}
    assert {t["id"] for t in subs if t["requires"]["archetype"] == "artificial_core"} == {
        "pop_n_swap", "extra_efficient_processor", "ether_furnace_overdrive"}
    assert {t["id"] for t in subs if t["requires"]["archetype"] == "flesh_eater"} == {
        "lease_on_life", "bond_forged_in_battle", "carry_on"}
    assert {t["id"] for t in subs if t["requires"]["archetype"] == "body_core_soul"} == {
        "sword_cross", "resynchronize", "explosive_emotion"}


def test_category_role_consistency(talents):
    for t in talents:
        if t["category"] == "universal":
            assert t["role"] == "any"
        elif t["category"] in ("bearer", "blade", "pair"):
            assert t["role"] == t["category"]


def test_talent_spot_checks(tmap):
    sb = tmap["social_butterfly"]
    assert sb["rank"] == 4 and sb["category"] == "universal" and sb["kind"] == "general"
    odb = tmap["orbital_death_beam"]
    assert (odb["rank"], odb["per"], odb["category"], odb["kind"], odb["role"]) == (10, "arc", "blade", "combat", "blade")
    fof = tmap["fleet_of_foot"]
    assert fof["rank"] == 5 and fof["requires"]["talents"] == ["quick_step"]
    assert fof["requires"]["attributes"] == {"swiftness": 5}
    assert tmap["quick_step"]["requires"]["attributes"] == {"swiftness": 3} and tmap["quick_step"]["rank"] == 3
    assert tmap["prime_position"]["requires"]["talents"] == ["secondary_accelerator"]
    assert tmap["prime_position"]["rank"] == 5 and tmap["secondary_accelerator"]["rank"] == 3
    # fame / infamy are ranged
    for tid in ("fame", "infamy"):
        t = tmap[tid]
        assert t["rank"] is None and (t["rank_min"], t["rank_max"]) == (1, 10)
    assert tmap["old_friends"]["repeatable"] is True
    assert sum(t["repeatable"] for t in tmap.values()) == 1
    assert tmap["just_a_flesh_wound"]["per"] == "once" and tmap["just_a_flesh_wound"]["rank"] == 10
    assert tmap["ghosts_of_the_past"]["creation_only"] and tmap["record_keeper"]["creation_only"]
    assert sum(t["creation_only"] for t in tmap.values()) == 2
    assert tmap["disciples_control"]["excludes"] == ["endbringers_power"]
    assert tmap["endbringers_power"]["excludes"] == ["disciples_control"]
    assert tmap["elite_healer"]["requires"]["talents"] == ["healer"]
    assert tmap["master_healer"]["requires"]["talents"] == ["elite_healer"]
    assert tmap["sandwiches"]["requires"]["talents"] == ["its_like_we_finish_each_others"]
    assert tmap["sandwiches"]["category"] == "pair"
    # HP talents, first strike
    assert [tmap[x]["rank"] for x in ("indomitable", "fortified", "steel_flesh")] == [2, 4, 6]
    assert "+3 to initiative" in tmap["first_strike"]["text"]
    assert tmap["living_amalgam"]["rank"] == 4 and "+4 HP" in tmap["living_amalgam"]["text"]
    assert tmap["radius_master"]["rank"] == 5 and tmap["swift_slide"]["requires"]["attributes"] == {"swiftness": 4}
    assert tmap["expeditionist"]["rank"] == 1
    assert tmap["building_through_conflict"]["rank"] == 3
    assert tmap["tactical_delay"]["rank"] == 1
    assert tmap["exit_strategy"]["requires"]["attributes"] == {"calculation": 8}
    assert tmap["exit_strategy"]["per"] == "arc"
    assert tmap["bond_sever"]["requires"]["attributes"] == {"attunement": 3}
    assert tmap["bondsight"]["requires"]["attributes"] == {"attunement": 7}
    assert tmap["no_not_yet"]["requires"]["attributes"] == {"willpower": 7}


def test_mascot_and_dying_devotion_text(tmap):
    m = tmap["mascot_character"]["text"]
    for opt in ("Eyes in The Sky", "Good Instincts", "Titan-in-Training", "Just the Cutest", "Natural Scavenger",
                "One With the Hunt"):
        assert opt + ":" in m
    dd = tmap["dying_devotion"]["text"]
    for name in ("Ghost Factory", "Living Amalgam", "Premonitions", "Forgotten Flash", "Summon Art", "Bondsight",
                 "Bond Sever", "Cut the Cord"):
        assert name in dd
    assert "one pool of HP" in dd


def test_untouched_and_telethial_text(tmap):
    assert "attunement is permanently reduced to 0" in tmap["untouched"]["text"]
    assert "three turns" in tmap["telethial"]["text"]
    assert "•" not in tmap["dying_devotion"]["text"]


# ------------------------------------------------------------------------------------------------ rules sections
def test_sections_schema(sections):
    assert 100 <= len(sections) <= 400
    ids = [s["id"] for s in sections]
    assert len(ids) == len(set(ids))
    chapters = set()
    for s in sections:
        assert set(s) == {"id", "chapter", "title", "page", "text"}
        assert re.fullmatch(r"[a-z0-9_]+", s["id"])
        assert isinstance(s["page"], int) and 0 <= s["page"] <= 91
        assert s["title"].strip() and s["chapter"].strip()
        chapters.add(s["chapter"])
        n = len(s["text"])
        assert 300 <= n <= 3200, (s["id"], n)
        for bad in ("↑", "↓", " ", "\t"):
            assert bad not in s["text"], (s["id"], repr(bad))
        assert not re.search(r"(?m)^\d{1,2}$", s["text"]), s["id"]       # stray page number
        assert "Blades of Ether by Alexis" not in s["text"]
    assert len(chapters) == 11


def test_sections_page_order(sections):
    pages = [s["page"] for s in sections]
    # book order: pages never go backwards except the reference tail (tables p85-86, sheet p88, quick refs p90-91)
    head = [s["page"] for s in sections if not s["chapter"].startswith("10")]
    assert head == sorted(head)
    tail = [s["page"] for s in sections if s["chapter"].startswith("10")]
    assert tail == sorted(tail)


KEYWORDS = ["Life Force Sharing", "Reconciliation", "Near Hit", "Blade Radius", "Special Dice", "Bond Points"]


@pytest.mark.parametrize("kw", KEYWORDS)
def test_keyword_coverage(sections, kw):
    hits = [s for s in sections if kw.lower() in (s["title"] + " " + s["text"]).lower()]
    assert hits, kw


def test_key_rules_present(sections):
    blob = "\n".join(s["text"] for s in sections)
    for phrase in (
        "each 5 or 6 shown represents a Success",
        "willpower + stamina + 4",
        "Bearers start with a movement of 3",
        "Blades take -1 to all actions when in their third radius",
        "costing two full special dice for a second-level attack",
        "Doing so costs the Blade one additional point of health",
        "Nothing Needs To Be Permanent",
        "Potency +1 (max 5)",
        "Pincer Attack (Blades only)",
        "Precise Attack (cost 10)",
        "2 x new rank",
    ):
        assert phrase in blob, phrase


def test_specific_sections(sections):
    by = {s["id"]: s for s in sections}
    assert "life_force_sharing" in by and "Life Force Sharing" in by["life_force_sharing"]["text"]
    assert "reconciliation_bursts" in by
    assert "Level 3" in by["reconciliation_bursts"]["text"] or "level 3" in by["reconciliation_bursts"]["text"]
    titles = [s["title"] for s in sections]
    for t in ("Titan: Gentarum", "Titan: The Waning Warriors", "Bestiary: Rockbart", "Blade Radius System",
              "Above the World Tree (rumors)", "Beneath the Cloud Sea (rumors)", "Modifying The Game"):
        assert t in titles, t
    for t in ("Glossary: Game Basics", "Glossary: Game Mechanics", "Glossary: World & Lore"):
        assert t in titles, t
    assert sum(t.startswith("Bestiary: ") for t in titles) == 8
    assert sum(t.startswith("Titan: ") for t in titles) == 9
    assert sum(t.startswith("Architect's Principles") for t in titles) == 3
    tag_tables = [s for s in sections if "Category | Category cost | Tags" in s["text"]]
    assert tag_tables and "Area of Effect | 15 |" in tag_tables[0]["text"]
    # the p.34 idea list is an erratum and is flagged as such
    assert any("[Erratum:" in s["text"] for s in sections)


def test_talent_sections_cover_all_talents(sections, talents):
    blob = "\n".join(s["text"] for s in sections if s["chapter"].startswith("6"))
    for t in talents:
        assert t["name"] + " (Rank" in blob, t["name"]


# ------------------------------------------------------------------------------------------------ bestiary
def test_bestiary_schema(bestiary):
    assert len(bestiary) == 8       # the book prints 8 example enemies in chapter 9
    ids = [e["id"] for e in bestiary]
    assert len(ids) == len(set(ids))
    for e in bestiary:
        assert set(e) == {"id", "name", "role", "attack", "defense", "hp", "movement", "initiative", "affinities",
                          "best_attributes", "art_tags", "special_abilities", "notes"}
        assert e["role"] in {"bearer", "blade", "other"}
        for k in ("attack", "defense"):
            assert set(e[k]) == {"dis", "normal", "adv"}
            assert e[k]["dis"] <= e[k]["normal"] <= e[k]["adv"]
        assert all(isinstance(e[k], int) and e[k] >= 0 for k in ("hp", "movement", "initiative"))
        assert e["hp"] > 0
        assert set(e["affinities"]) <= ELEMENTS
        assert set(e["best_attributes"]) <= ATTRS
        assert set(e["art_tags"]) <= TAG_IDS
        for s in e["special_abilities"]:
            assert set(s) == {"name", "text"} and s["name"] and s["text"]


def test_bestiary_values(bestiary):
    b = {e["id"]: e for e in bestiary}
    assert set(b) == {"pack_animal", "elemental_ursine", "novice_bearer", "forgeling_blade", "blade_eater",
                      "legendary_bearer", "titanic_blade", "rockbart"}
    r = b["rockbart"]
    assert (r["hp"], r["initiative"], r["movement"]) == (90, 10, 4)
    assert r["attack"] == {"dis": 6, "normal": 7, "adv": 8} and r["defense"] == {"dis": 4, "normal": 5, "adv": 6}
    assert r["affinities"] == ["earth"] and r["best_attributes"] == ["might"]
    assert r["art_tags"] == ["break", "topple", "launch"] and r["role"] == "other"
    p = b["pack_animal"]
    assert (p["hp"], p["movement"], p["initiative"]) == (5, 3, 3)
    assert p["attack"] == {"dis": 1, "normal": 2, "adv": 3} and p["defense"] == {"dis": 0, "normal": 1, "adv": 2}
    assert p["special_abilities"][0]["name"] == "Howl"
    u = b["elemental_ursine"]
    assert (u["hp"], u["movement"], u["initiative"]) == (16, 4, 3) and u["art_tags"] == ["unique_effect"]
    assert u["best_attributes"] == ["gut", "stamina"] and u["affinities"] == []
    n = b["novice_bearer"]
    assert (n["hp"], n["movement"], n["initiative"], n["role"]) == (5, 3, 2, "bearer")
    assert n["art_tags"] == [] and "Pick three" in n["notes"]
    f = b["forgeling_blade"]
    assert (f["hp"], f["movement"], f["initiative"], f["role"]) == (5, 1, 2, "blade")
    e = b["blade_eater"]
    assert (e["hp"], e["movement"], e["initiative"], e["role"]) == (15, 5, 3, "bearer")
    assert e["defense"] == {"dis": 1, "normal": 2, "adv": 2}
    assert e["art_tags"] == ["unique_effect", "break", "topple", "launch", "stagger", "rush"]
    lb = b["legendary_bearer"]
    assert (lb["hp"], lb["movement"], lb["initiative"]) == (25, 4, 4)
    assert lb["attack"] == lb["defense"] == {"dis": 4, "normal": 5, "adv": 7}
    tb = b["titanic_blade"]
    assert (tb["hp"], tb["movement"], tb["initiative"], tb["role"]) == (25, 2, 5, "blade")


# ------------------------------------------------------------------------------------------------ examples
def test_examples(examples, tmap):
    assert set(examples) == {"bonds", "field_skills", "titans", "titan_questions", "rumors"}
    assert len(examples["bonds"]) == 13
    assert [b["name"] for b in examples["bonds"]][:2] == ["Best Friend", "Coworker"]
    assert "Unrequited Love" in [b["name"] for b in examples["bonds"]]
    assert len(examples["field_skills"]) == 15
    assert "Elemental Mastery" in [b["name"] for b in examples["field_skills"]]
    assert [t["name"] for t in examples["titans"]] == ["Gentarum", "Morgot", "Raya", "Mordania", "Leftria", "Idnol",
                                                       "Bengu", "Ronat", "The Waning Warriors"]
    assert len(examples["titan_questions"]) == 8
    assert examples["titan_questions"][0]["name"] == "What is the Titan's shape?"
    r = examples["rumors"]
    assert [x["name"] for x in r["above_world_tree"]] == ["Paradise", "Space Station", "Life's Cradle", "Branches"]
    assert [x["name"] for x in r["beneath_cloud_sea"]] == ["Ancient Ruins", "Living Societies", "Dimensional Tear",
                                                          "Titan Corpses"]
    for coll in (examples["bonds"], examples["field_skills"], examples["titans"], examples["titan_questions"],
                 r["above_world_tree"], r["beneath_cloud_sea"]):
        for item in coll:
            assert set(item) == {"name", "text"} and item["name"] and len(item["text"]) > 20
            assert "\n" not in item["text"] and "  " not in item["text"]
