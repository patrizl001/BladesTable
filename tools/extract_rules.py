"""Split the whole rulebook into retrieval-sized sections (boe/data/rules_sections.json)."""
import json
import re

from pdfblocks import all_pages, clean, reflow
import rules_stream as rs

OFF = 5
DROP_TEXT = {"Untouched Talents", "Telethial Talents", "Artificial Core Talents", "Flesh Eater Talents",
             "Body, Core, and Soul Talents"}

CH = {
    0: "Front Matter", 1: "1: Bearers, Blades, and Beyond", 2: "2: Beating the Odds", 3: "3: The Players",
    4: "4: Combat", 5: "5: Character Creation and Progression", 6: "6: List of Talents",
    7: "7: The World of Arlest", 8: "8: The Architect", 9: "9: Example Bestiary", 10: "10: Reference Materials",
}

# ---------------------------------------------------------------------------------------------------------
# Section plan, in book order.  ("s", chapter, title, marker)   stream section starting at the paragraph
#                                                              whose text starts with `marker`
#                              ("i", key, marker)              stream intro text kept for a generated section
#                              ("g", chapter, key)             generated section(s)
# A stream section ends where the next "s" or "i" entry starts.
# ---------------------------------------------------------------------------------------------------------
PLAN = [
    ("s", 0, "Introduction: The World of Arlest and its Titans", "As far as the eye can see"),
    ("s", 0, "Introduction: Blades, Bearers and the Bond", "There is only one thing that every Titan-based"),
    ("s", 0, "Credits and License", "For more information, to download a digitally"),
    ("s", 1, "Chapter 1 Introduction: Welcome to Blades of Ether", "Throughout the eras"),
    ("s", 1, "The Architect", "The world of Arlest may already be defined"),
    ("s", 1, "Teams", "The party, the full group of all players"),
    ("s", 1, "Blades", "Ether is an intangible force"),
    ("s", 1, "Bearers and The Adventure", "In order to forge a Blade"),
    ("s", 2, "Beating the Odds: Introduction", "Some dismiss luck"),
    ("s", 2, "Rolling the Dice: Dice Pools, Successes, Checks, Near Hits and Near Misses", "Like in many tabletop games"),
    ("s", 2, "Dice Pool Modifiers (with Example of Play: a salvaging run)", "Certain properties of a character"),
    ("s", 2, "Purpose in Pips: One Roll per Uncertain Action", "Arlest is a fast, dynamic place"),
    ("s", 2, "Purpose in Pips: Net Successes and Letting the Narrative Guide the Mechanics", '"Victory" or "failure"'),
    ("s", 2, "Forming a Dice Pool", "When a player declares an action"),
    ("s", 2, "Forming a Dice Pool: Any Attribute Can Work (with Example of Play: Bridget investigates)",
     "Any attribute can be used for any action"),
    ("s", 3, "Attributes and Ideas: Overview", "The powers Bearers and Blades share"),
    ("s", 3, "Idea: Bravery (Might, Willpower, Calculation)", "Bravery: Drawing your sword"),
    ("s", 3, "Idea: Truth (Gut, Experience, Knowledge)", "Truth: What you know"),
    ("s", 3, "Idea: Compassion (Stamina, Empathy, Attunement)", "Compassion: Nothing worth doing"),
    ("s", 3, "Idea: Justice (Swiftness, Improvisation, Passion) and Idea Values", "Justice: What is right"),
    ("s", 3, "Combat Basics", "In combat, characters have three forms"),
    ("s", 3, "Traits: Basic Attack Range, HP, Initiative, Movement", "Characters have four Traits"),
    ("s", 3, "Elemental Affinity", "Blades are made of ether."),
    ("s", 3, "Bonds and Affinity: Overview", "When a Bearer and a Blade come together"),
    ("s", 3, "Bond Components: Name, Benefit, Drawback", "Name: a short description"),
    ("s", 3, "Affinity (-2 to +2)", "Affinity: a number from -2"),
    ("s", 3, "Reconciliation Bursts", "Bonds at high affinity will naturally fall off"),
    ("s", 3, "Example Bonds: Best Friend, Coworker, I Hate Their Guts, Leader, Lover", "Best Friend:"),
    ("s", 3, "Example Bonds: My Mentee, My Mentor, My Guardian, My Ward, Owe Them a Debt, Rival, Uneasy Ally, "
             "Unrequited Love", "My Mentee:"),
    ("s", 3, "Play Tips: Roleplaying Bonds", "Bonds and affinity are core mechanics"),
    ("s", 3, "Play Tips: Roleplaying Bonds (the limits of the mechanics)", "Finally, Blades of Ether as a game"),
    ("s", 3, "Combats, Sessions, and Arcs", "Gameplay is divided along several units of time"),
    ("s", 3, "Once-Per-Arc Abilities: I'm Really Feeling It, It's Reyn Time, The Heronop Special",
     "Many abilities characters can have specify"),
    ("s", 3, "Weapons", "After Blades' etheric"),
    ("s", 3, "Talents", "Over the course of an adventure"),
    ("s", 3, "Field Skills: Overview and Use", "Every character has things they excel at"),
    ("s", 3, "Field Skills: Combat, Tools, and Creation", "Field skills are usually non-violent"),
    ("s", 3, "Example Field Skills", "Animal Handling:"),
    ("s", 4, "Combat: Introduction", "Nothing tests the unity"),
    ("s", 4, "The Grid, Initiative, and Turns: Grid and Initiative", "In Blades of Ether, combat is played using tokens"),
    ("s", 4, "Team Initiative Slots and Turn Swaps", "The initiative values rolled by players"),
    ("s", 4, "Turn Order Tokens and Turn Structure (with Example of Play: turn order)",
     "Once you have rolled initiative and decided"),
    ("s", 4, "Movement and Facing: Moving on the Grid", "In order to attack the enemy, one must first"),
    ("s", 4, "Blade Radius System", "Blades, being fundamentally immaterial"),
    ("s", 4, "Radius Changes When a Bearer Moves", "Since Blade radii are centered on their Bearer"),
    ("s", 4, "Facing (with Example of Play: moving and facing)", "In addition to one's place on the grid"),
    ("s", 4, "Attacking and Defending: Range and Line of Sight", "Once you've moved into position"),
    ("s", 4, "Attacking and Defending: Rolling, Near Hits, Near Misses and Damage",
     "Though attacks have some unique mechanics"),
    ("s", 4, "Basic Attacks (with Example of Play: Doma defends)", "Basic attacks, the first of"),
    ("s", 4, "Arts: Overview, Cooldowns and Starting Cooldowns", "Arts are your signature moves"),
    ("s", 4, "Art Tags: Categories, Category Cost and the Art Tags Table", "Arts customization uses a tag system"),
    ("s", 4, "Tag Category: Fundamentals (Potency, Healing Potion, Cooldown)", "Fundamentals (category cost 3)"),
    ("s", 4, "Tag Category: Area of Effect (Circle Attack, Line Attack)", "Area of Effect (category cost 15)"),
    ("s", 4, "Tag Category: Reactions (Break, Topple)", "Reactions (category cost 5)"),
    ("s", 4, "Tag Category: Reactions (Launch, Stagger, Rush)", "Launch: force a broken target"),
    ("s", 4, "Tag Category: Positionals (Side, Rear, Pincer)", "Positionals (category cost 3)"),
    ("s", 4, "Tag Category: Elemental Effects (overview and durations)", "Elemental Effects (category cost 4)"),
    ("s", 4, "Unique Elemental Effects: Burning Blade, Arts Seal, Blustering Gale, Freezing Force",
     "Unique Elemental Effect: draw on the power"),
    ("s", 4, "Unique Elemental Effects: Cradling Earth, Electrifying Burst, Blade of Light, Shadow Manipulation",
     "Cradling Earth (earth)"),
    ("s", 4, "Shared Elemental Effects: Invigorating Steam, Bitter Snowstorm, Counter Spike, Blinding Eclipse",
     "Invigorating Steam (bravery, requires"),
    ("s", 4, "Other Tags: Range +1 and Precise Attack", "Other tags (cost varies)"),
    ("s", 4, "Example of Play: an Art Attack (Gemini Round)", "Knowing Doma's turn is next"),
    ("s", 4, "Special Attacks: Special Points and Special Dice", "As battle flows, tension builds"),
    ("s", 4, "Special Attack Levels, Combinations and Party Size Rules", 'A "full" special die showing a 6'),
    ("s", 4, "Special Attacks: Ideas, Elemental Effects, Range and Damage",
     "Once a team has the requisite special dice"),
    ("s", 4, "HP and Falling in Battle", "Actions and effects in combat deal damage"),
    ("s", 4, "Life Force Sharing", "Due to the connection Blades share"),
    ("s", 4, "Unconsciousness, Core Form and Recovering HP", "When a material combatant such as a Bearer hits 0 HP"),
    ("s", 4, "Play Tips: On Violence and Killing (combat versus violence)", "This game focuses very heavily on combat"),
    ("s", 4, "Play Tips: Player versus Player Combat", "Teammate tension tip"),
    ("s", 4, "Play Tips: Death and Killing Player Characters", "The numeric HP rules say nothing of death"),
    ("s", 4, "Action in Action: Initiative and Turn Order", "This section presents a complete example"),
    ("s", 4, "Action in Action: Pyre's Turn (art attack and bookkeeping)", "A few turns in, Pyre is up"),
    ("s", 4, "Action in Action: The Enemy Blade's Turn (line attack and defense)", "Next is the enemy Blade's turn"),
    ("s", 4, "Action in Action: A Level 2 Special Attack", "A number of rounds of combat pass"),
    ("s", 5, "Chapter 5 Introduction: Character Creation and Progression", "It is said that every Blade and Bearer"),
    ("s", 5, "Character Creation: Basic Information", "The first thing you must do is establish"),
    ("s", 5, "Character Creation: Starting Point", "How long have you been traveling for?"),
    ("s", 5, "Character Creation: Attributes", "The raw strength of a Blade or Bearer can be measured"),
    ("s", 5, "Character Creation: Elemental Affinity and Traits", "Beneath a character's attributes is space"),
    ("s", 5, "Character Creation: Field Skills", "Directly below the attributes box"),
    ("s", 5, "Character Creation: Bonds and Trackers", "On the bottom of the front of the character sheet"),
    ("s", 5, "Character Creation: Arts and Art Tags at Creation", "The three boxes on the right side"),
    ("s", 5, "Character Creation: Talents", "On the back of your character sheet"),
    ("s", 5, "Inventory and Notes", "Blades of Ether does not have you track resources"),
    ("s", 5, "The Dead Box", "At the top of your character sheet is a checkbox"),
    ("s", 5, "Character Creation Starting Points (table)", "Character Creation Starting Points. Attributes"),
    ("s", 5, "Progression and Bond Points: Earning BP (with Example of Play)", "The true strengths of Bearers and Blades"),
    ("s", 5, "Spending Bond Points: Upgrade Costs and Examples", "Between sessions, you may spend"),
    ("s", 5, "Refunding Arts Tags", "Building an art that feels exactly"),
    ("s", 6, "Chapter 6 Introduction: Talents", "Whether learned or instinctual"),
    ("i", "bearer_intro", "Maintaining the etheric bond"),
    ("i", "blade_intro", "Blades are people who are etheric"),
    ("i", "pair_intro", "Blades and Bearers are at their best"),
    ("i", "archetype_intro", "Blade or Bearer, there's something special"),
    ("g", 6, "talents_universal_general"),
    ("g", 6, "talents_universal_combat"),
    ("g", 6, "talents_bearer_general"),
    ("g", 6, "talents_bearer_combat"),
    ("g", 6, "talents_blade_general"),
    ("g", 6, "talents_blade_combat"),
    ("g", 6, "talents_pair"),
    ("g", 6, "talents_archetype_overview"),
    ("g", 6, "talents_untouched"),
    ("g", 6, "talents_telethial"),
    ("s", 6, "Archetype Example (Telethial and Untouched): Janae and Jun (1 of 2)", "To any onlooker, Jun and Janae"),
    ("s", 6, "Archetype Example (Telethial and Untouched): Janae and Jun (2 of 2)", "\u2026 Eventually, Jun awoke"),
    ("g", 6, "talents_artificial_core"),
    ("g", 6, "talents_flesh_eater"),
    ("s", 6, "Archetype Example (Artificial Core and Flesh Eater): Aria and Eryn (1 of 2)", "The rain bounced off Aria"),
    ("s", 6, "Archetype Example (Artificial Core and Flesh Eater): Aria and Eryn (2 of 2)", "Aria fell to her knees"),
    ("g", 6, "talents_dying_devotion"),
    ("g", 6, "talents_body_core_soul"),
    ("s", 7, "Chapter 7 Introduction: The World of Arlest and Titans of Arlest", "Although Arlest is mostly composed"),
    ("s", 7, "Titan: Gentarum", "Gentarum is technically not a Titan"),
    ("s", 7, "Titan: Morgot", "Morgot is one of the largest Titans"),
    ("s", 7, "Titan: Raya", "The whale Titan Raya"),
    ("s", 7, "Titan: Mordania", "The bipedal humanoid Mordania"),
    ("s", 7, "Titan: Leftria", "Leftria is the collective name"),
    ("s", 7, "Titan: Idnol", "The draconic Titan of Idnol"),
    ("s", 7, "Titan: Bengu", "Bengu is a bit of an odd case"),
    ("s", 7, "Titan: Ronat", "The large, serpent-like Ronat"),
    ("s", 7, "Titan: The Waning Warriors", "On the far side of the Cloud Sea"),
    ("s", 7, "Creating Titans", "The world of Arlest contains many Titans beyond"),
    ("s", 7, "Creating Titans: Questions (shape, population, inhabitants, ecosystem)", "What is the Titan's shape?"),
    ("s", 7, "Creating Titans: Questions (government, Blades, renown, dangers)",
     "What is the population's governmental structure?"),
    ("s", 7, "Above the World Tree (rumors)", "Although some claim to have successfully climbed"),
    ("s", 7, "Beneath the Cloud Sea (rumors)", "Getting below the Cloud Sea"),
    ("s", 8, "Chapter 8 Introduction: The Architect", "It is common knowledge that the Architect"),
    ("s", 8, "Architect's Principles (1 of 3): Fan of the Characters, Quiet Moments, Vivid Color, Whimsy",
     "As the Architect, your role is essential"),
    ("s", 8, "Architect's Principles (2 of 3): Let the Players Lead, Unexpected Outcomes, Nothing Needs To Be Permanent",
     "Let the Players Lead the Charge"),
    ("s", 8, "Architect's Principles (3 of 3): Let Them Be Incredible, Play to Find Out What Happens",
     "Let Them Be Incredible"),
    ("s", 8, "Rolling, Failure, and Consequences: Exploring Interesting Success", "One of your more important jobs"),
    ("s", 8, "Creating Interesting Failure", "When someone rolls, something will always happen"),
    ("s", 8, "Using Near Hits and Near Misses: Definitions", "On a near hit, when a player garners"),
    ("s", 8, "Using Near Hits and Near Misses: Spotlight and Mitigation", "Near hits and near misses are powerful tools"),
    ("s", 8, "On Bonds and Affinity (advice for the Architect)", "If you're unsure when a bond has changed"),
    ("s", 8, "On Non-Player Characters", "Creating Architect-controlled"),
    ("s", 8, "On Non-Player Characters: Keeping the Cast Small", "There's a very thin line to tread"),
    ("s", 8, "Creating Encounters and Creating Maps", "When the time to fight comes"),
    ("s", 8, "Creating Enemies: Name, Role, Attacks, Defenses", "You've made your maps and filled them"),
    ("s", 8, "Creating Enemies: Movement, Initiative, HP, Elemental Affinity, Best Attributes",
     "Movement: how far this enemy can move"),
    ("s", 8, "Creating Enemies: Art Tags, Special Abilities, Notes", "Art Tags: any tags that will be on enemy attacks"),
    ("s", 8, "Enemy Cards: NPC Cards and Generic Enemies", "To describe your enemies, you can use this card"),
    ("s", 8, "Balancing Enemies: Player Attributes and Dice Pool Results (table)", "For balancing enemies relative"),
    ("s", 8, "Controlling Combat: Fun over Winning", "You've got your map, you've got your enemies"),
    ("s", 8, "Controlling Combat: Advantaged and Disadvantaged Numbers, Hidden Cards, Allied NPCs",
     "An important aspect of controlling enemies"),
    ("s", 8, "Modifying The Game", "One of the advantages of tabletop roleplaying games"),
    ("s", 8, "The First Session: Safety, Tone and Preparation", "Before you start your first session"),
    ("s", 8, "The First Session: Bringing the Party Together", "One key part of any first session"),
    ("s", 9, "Example Bestiary: Introduction", "The larger one's impact"),
    ("g", 9, "bestiary"),
    ("s", 10, "Reference Materials: Introduction", "You've packed your bag"),
    ("g", 10, "glossary"),
    ("g", 10, "reference_tables"),
    ("g", 10, "quickref"),
]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower().replace("'", "")).strip("_")


# ---------------------------------------------------------------------------------------------------------
def talent_sections(talents, group, pages_text, intro_by_group):
    """Generated talent sections for one group, chunked at talent boundaries to <= ~2400 chars."""
    id_name = {t["id"]: t["name"] for t in talents}

    def head(t):
        rank = t["rank"] if t["rank"] is not None else "%d-%d" % (t["rank_min"], t["rank_max"])
        extra = []
        req = t["requires"]
        r = ["%d %s" % (v, k) for k, v in req["attributes"].items()] + [id_name[x] for x in req["talents"]]
        if req["archetype"]:
            r.append("archetype " + id_name[req["archetype"]])
        if r:
            extra.append("Requires " + " and ".join(r))
        if t["excludes"]:
            extra.append("Cannot be taken with " + ", ".join(id_name[x] for x in t["excludes"]))
        if t["creation_only"]:
            extra.append("Character creation only")
        if t["per"]:
            extra.append({"arc": "once per arc", "session": "once per session", "combat": "once per combat",
                          "once": "once only"}[t["per"]])
        if t["repeatable"]:
            extra.append("may be taken multiple times")
        return "%s (Rank %s%s): %s" % (t["name"], rank, "; " + "; ".join(extra) if extra else "", t["text"])

    return [(t["page"], head(t), t["name"]) for t in talents]


def chunk_entries(entries, intro, limit=2800):
    """entries: [(page, text, label)] -> [(page, text, first_label, last_label)] with intro in first chunk."""
    chunks, cur, cur_len = [], [], 0
    for e in entries:
        if cur and cur_len + len(e[1]) > limit:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(e)
        cur_len += len(e[1])
    if cur:
        chunks.append(cur)
    res = []
    for i, c in enumerate(chunks):
        text = "\n\n".join(e[1] for e in c)
        if i == 0 and intro:
            text = intro + "\n\n" + text
        res.append((c[0][0], text, c[0][2], c[-1][2], len(chunks)))
    return res


def talent_group_sections(talents, intros):
    T = talents

    def sel(**kw):
        return [t for t in T if all((t[k] == v) for k, v in kw.items())]

    groups = [
        ("talents_universal_general", "Universal Talents: General", sel(category="universal", kind="general"), None),
        ("talents_universal_combat", "Universal Talents: Combat", sel(category="universal", kind="combat"), None),
        ("talents_bearer_general", "Bearer Talents: General", sel(category="bearer", kind="general"), intros["bearer_intro"]),
        ("talents_bearer_combat", "Bearer Talents: Combat", sel(category="bearer", kind="combat"), None),
        ("talents_blade_general", "Blade Talents: General", sel(category="blade", kind="general"), intros["blade_intro"]),
        ("talents_blade_combat", "Blade Talents: Combat", sel(category="blade", kind="combat"), None),
        ("talents_pair", "Pair Talents", sel(category="pair"), intros["pair_intro"]),
    ]
    out = {}
    for key, title, ts, intro in groups:
        entries = talent_sections(ts, key, None, None)
        chunks = chunk_entries(entries, intro)
        res = []
        for page, text, first, last, n in chunks:
            t = title if n == 1 else ("%s (%s)" % (title, first) if first == last else "%s (%s to %s)" % (title, first, last))
            res.append({"chapter": CH[6], "title": t, "page": page, "text": text})
        out[key] = res
    # archetypes: each archetype with its sub-talents
    arch_ids = {"talents_untouched": "untouched", "talents_telethial": "telethial",
                "talents_artificial_core": "artificial_core", "talents_flesh_eater": "flesh_eater",
                "talents_dying_devotion": "dying_devotion", "talents_body_core_soul": "body_core_soul"}
    names = {t["id"]: t["name"] for t in T}
    for key, aid in arch_ids.items():
        ts = [t for t in T if t["id"] == aid] + [t for t in T if t["requires"]["archetype"] == aid]
        entries = talent_sections(ts, key, None, None)
        chunks = chunk_entries(entries, None, limit=3000)
        res = []
        for page, text, first, last, n in chunks:
            title = "Archetype Talent: %s%s" % (names[aid], "" if aid == "dying_devotion" else " and its Talents")
            if n > 1:
                title += " (%s to %s)" % (first, last)
            res.append({"chapter": CH[6], "title": title, "page": page, "text": text})
        out[key] = res
    out["talents_archetype_overview"] = [{
        "chapter": CH[6], "title": "Archetype Talents: Overview", "page": 52, "text": intros["archetype_intro"]}]
    return out


# ---------------------------------------------------------------------------------------------------------
def bestiary_sections(enemies):
    res = []
    for e in enemies:
        a, d = e["attack"], e["defense"]
        lines = ["%s (Role: %s). Attacks (disadvantaged / normal / advantaged): %d / %d / %d. Defenses: %d / %d / %d. "
                 "HP %d. Movement %d. Initiative %d." % (e["name"], e["role"], a["dis"], a["normal"], a["adv"],
                                                       d["dis"], d["normal"], d["adv"], e["hp"], e["movement"],
                                                       e["initiative"])]
        if e["affinities"]:
            lines.append("Elemental affinities: %s." % ", ".join(e["affinities"]))
        if e["best_attributes"]:
            lines.append("Best attributes: %s." % ", ".join(e["best_attributes"]))
        if e["art_tags"]:
            lines.append("Art tags: %s." % ", ".join(e["art_tags"]))
        for s in e["special_abilities"]:
            lines.append("Special ability - %s: %s" % (s["name"], s["text"]))
        if e["notes"]:
            lines.append("Notes: " + e["notes"])
        res.append({"chapter": CH[9], "title": "Bestiary: " + e["name"], "page": e["page"], "text": "\n".join(lines)})
    return res


# ---------------------------------------------------------------------------------------------------------
GLOSS_ZONES = [
    # (pdf page, y_min, y_max, group)
    (86, 255, 593, "Game Basics"), (86, 593, 800, "Game Mechanics"),
    (87, 0, 396, "Game Mechanics"), (87, 396, 800, "Character Components"),
    (88, 0, 297, "Character Components"), (88, 297, 800, "Combat"),
    (89, 0, 800, "Combat"),
    (90, 0, 212, "Combat"), (90, 212, 490, "World & Lore"),
]


def glossary_sections(pdf):
    pages = all_pages(pdf)
    entries = {}     # group -> [(printed page, text)]
    order = []
    for pg, y0, y1, group in GLOSS_ZONES:
        blocks = [b for b in pages[pg] if y0 <= b["y"] < y1 and not (len(b["lines"]) == 1 and max(b["heights"]) >= 14)
                  and not (re.fullmatch(r"\d+", b["lines"][0].strip()) and b["y"] > 735)]
        blocks.sort(key=lambda b: (0 if b["x"] < 300 else 1, b["y"]))
        lst = entries.setdefault(group, [])
        if group not in order:
            order.append(group)
        for b in blocks:
            text = reflow(b["lines"])
            if lst and lst[-1][1] and not rs.TERMINAL.search(lst[-1][1]) and text[:1].islower():
                lst[-1] = (lst[-1][0], reflow([lst[-1][1], text]))
            else:
                lst.append((pg - OFF, text))
    out = []
    for group in order:
        lst = entries[group]
        chunks, cur, n = [], [], 0
        for e in lst:
            if cur and n + len(e[1]) > 2400:
                chunks.append(cur)
                cur, n = [], 0
            cur.append(e)
            n += len(e[1]) + 1
        chunks.append(cur)
        for c in chunks:
            first = re.split(r" \(|:", c[0][1])[0]
            last = re.split(r" \(|:", c[-1][1])[0]
            title = "Glossary: %s" % group if len(chunks) == 1 else "Glossary: %s (%s to %s)" % (group, first, last)
            out.append({"chapter": CH[10], "title": title, "page": c[0][0], "text": "\n".join(e[1] for e in c)})
    return out


# ---------------------------------------------------------------------------------------------------------
QUICKREF = [
    {"title": "Quick Reference: Core Dice Mechanics and Once-Per-Arc Special Abilities", "page": 90,
     "text": (
         "Core Dice Mechanics\n"
         "Rolling Dice: Roll a Dice Pool which consists of an Attribute and any relevant bonuses. Any Successes "
         "(5s or 6s rolled) beyond the Check (difficulty) are Net Successes.\n"
         "Dice Roll Results: Just one net success is a Near Hit, and victory comes with an unexpected consequence; "
         "zero net successes is a Near Miss, and failure comes with a small benefit.\n"
         "Once-Per-Arc Special Abilities\n"
         "I'm Really Feeling It: Add one Attribute to Initiative roll, and gain 6 Special Points.\n"
         "It's Reyn Time: Guarantee roll success.\n"
         "The Heronop Special: Turn failed roll into Near Miss.")},
    {"title": "Quick Reference: Combat Turns, Movement and End of Turn Reminders", "page": 90,
     "text": (
         "Combat Turns\n"
         "On Your Turn: On your turn in combat, you may Move, perform an Action (any one dice roll; most often an "
         "Attack), and freely change the direction you're Facing.\n"
         "Movement\n"
         "Move from one orthogonal, adjacent square to another. Diagonal squares are 2 squares apart. Movement can "
         "be split before and after an action.\n"
         "Non-Blades: Move a number of squares per turn equal to your Movement trait.\n"
         "Blades: You can freely move about the squares in your current Radius and change radii a number of times "
         "equal to your Movement trait. Take -1 in third radius; roll at half (rounded up) and move one square per "
         "turn outside radii.\n"
         "Distance: If you don't attack, take double movement.\n"
         "Radius Changes: If Bearer moves, choose nearest square in previous radius or stay in place, changing "
         "radii. If Bearer is moved, stay in place.\n"
         "Facing: You may face any cardinal direction. Choose a direction at the end of your turn.\n"
         "End of Turn Reminders\n"
         "- Choose Facing.\n"
         "- If Blade, choose a square to stay in.\n"
         "- Gain a Special Point if your basic attack or art hit.\n"
         "- Turn Cooldown Dice 1 lower. 1s turned are removed; art is ready.\n"
         "- Move Turn Order Token from top of turn order list to bottom.")},
    {"title": "Quick Reference: Attacking and Defending, Special Attack Levels, Party Size Rules", "page": 90,
     "text": (
         "Attacking and Defending\n"
         "Attack: Name a target within your attack's Range (distance in squares) and perform a standard dice roll to "
         "attack. Face your target; they Face you after the attack.\n"
         "Defend: Standard dice roll to defend. Turn to Face attacker.\n"
         "Basic Attack: Range = Basic Attack Range trait. Typically no bonuses. Successful attacks grant one "
         "Special Point.\n"
         "Art: Range = 1 + Range +1 Art tags. Target might be an Area of Effect. Potency +1 and Positional tags "
         "grant bonus dice. Beneficial effects apply regardless of range and success. Arts have Cooldowns. "
         "Successful attacks grant one Special Point.\n"
         "Special Attack: Range = anywhere. Higher levels are Area of Effect. Each special increases the Special "
         "Level of the next one. Expend Special Level x 6 Special Points to use. Dice pools use Ideas; roll "
         "unopposed. Applies one Elemental Effect from elements aligned with the idea.\n"
         "Special Attack Levels\n"
         "1: Cost 6. Target one enemy; roll chosen idea; apply one aligned elem. effect.\n"
         "2: Cost 12. Split damage among any enemies in a 3x3 area; you and your partner each roll your chosen idea; "
         "apply one aligned elem. effect to all hit.\n"
         "3: Cost 18. Split among 5x5 area; each choose an idea to roll; apply one elem. effect from either idea to "
         "all hit. Resets Special Level to 1.\n"
         "Party Size Special Attack Rules\n"
         "1 Team: Specials 1 and 2 do not consume Special Points.\n"
         "2 Teams: One team receives 6 Special Points when the other uses a Level 2 Special.\n"
         "3+ Teams: No changes.")},
    {"title": "Quick Reference: Art Tag Effects (Fundamentals, Area of Effect, Reactions, Positionals)", "page": 91,
     "text": (
         "Art Tag Effects. Legend: * = has important, complex mechanics; (+) = has a beneficial effect with a "
         "duration; (-) = has a detrimental effect with a duration.\n"
         "Fundamentals\n"
         "Potency +1 (max 5): +1 to attack.\n"
         "Healing Potion: One ally heals net successes.\n"
         "Cooldown -1 (max 2): Start cooldown Die 1 lower.\n"
         "Area of Effect\n"
         "Circle Attack (max 2): Target all enemies in a 3x3 area; lv. 2 for 5x5 area.\n"
         "Line Attack: Target all enemies in a straight line 5 + Bonus Range long.\n"
         "Reactions\n"
         "* (-) Break: Hit target is Broken, vulnerable to Topple and Launch, until your next turn. Can be extended "
         "by whole turn cycles.\n"
         "* (-) Topple: Requires and removes Break. Target cannot move or attack until your next turn. They can "
         "defend, but failed attacks are Near Hits. Take an action to un-topple an adjacent ally. Cannot be "
         "extended.\n"
         "* Launch: Requires and removes Break. Target is pushed net successes squares away. Object collision deals "
         "damage = squares from stopping. Hit combatant takes damage = squares from stopping. If no object "
         "collision, target moves back in the turn order one place.\n"
         "Stagger: Hit target moves back in the turn order one place.\n"
         "Rush (max 2): Movement +1.\n"
         "Positionals\n"
         "Side Advantage (Bearers): Attack from side for +1.\n"
         "Rear Advantage (Bearers): Attack from behind for +2.\n"
         "Pincer Attack (Blades): Gain +2 against target in lower radius.")},
    {"title": "Quick Reference: Art Tag Effects (Elemental Effects and Other Tags)", "page": 91,
     "text": (
         "Elemental Effects\n"
         "Using one requires appropriate Elemental Affinity. Pick one of these for every Special Attack. Maximum "
         "effect duration is 6.\n"
         "* Unique Elemental Effect: choose any one effect corresponding to one of your affinities:\n"
         "(-) Fire (Burning Blade): Target takes 1 damage per turn for net successes turns.\n"
         "(-) Water (Arts Seal): Target cannot use arts and do not lower cooldowns on their next turn.\n"
         "(+) Wind (Blustering Gale): Ally gets +1 defense for net successes turns.\n"
         "(-) Ice (Freezing Force): Target cannot move next turn. Frozen Bearer = Blade cannot change radii.\n"
         "(+) Earth (Cradling Earth): Ally removes and blocks all detrimental effects until your next turn.\n"
         "Electricity (Electrifying Burst): Target moves back in the turn order or ally moves forward in the turn "
         "order one place.\n"
         "(+) Light (Blade of Light): Ally Bearer gains +2 range for net successes turns, or ally Blade moves freely "
         "among all radii with no penalties during their next turn.\n"
         "(-) Dark (Shadow Manipulation): Redirect enemy attacks to chosen ally for net successes turns.\n"
         "Invigorating Steam (bravery, fire or water): One ally uses one art one turn sooner.\n"
         "(-) Bitter Snowstorm (truth, wind or ice): Target takes -1 movement (min 0) and attack range (min 1) for "
         "net successes turns.\n"
         "(+) Counter Spike (compassion, earth or electricity): Anyone who attacks you takes 1 damage back for net "
         "successes turns.\n"
         "(-) Blinding Eclipse (justice, light or dark): Target takes -1 to attack and defense rolls until after "
         "your next turn.\n"
         "Other Tags\n"
         "Precise Attack: Detrimental effects do not hit allies.\n"
         "Range +1 (max 5): +1 attack range.")},
]


def reference_table_sections():
    return [
        {"chapter": CH[10], "title": "Reference Tables: Character Creation Starting Points and Upgrade Bond Points Costs",
         "page": 85, "text": rs.T_START + "\n\n" + rs.T_UPGRADE},
        {"chapter": CH[10], "title": "Reference Tables: Art Tags at Character Creation (cost in tags)", "page": 86,
         "text": rs.T_CREATION_TAGS.split("\nExample art")[0]},
        {"chapter": CH[10], "title": "Reference Tables: Art Tags (category cost in bond points)", "page": 86,
         "text": rs.T_ART_TAGS},
        {"chapter": CH[10], "title": "Character Sheet Quick-Reference Footer", "page": 88,
         "text": ("Character creation: Basic attack range = 1. HP = willpower + stamina + 4. Initiative = improvisation + "
                  "gut or calculation + experience. Movement = 3 for Bearers, 1 for Blades. Bond points costs: Attribute "
                  "= 2 x new rank. Elem. affinity = 7 x total affinities. Field skill = 3. Talent = 3 x rank. Basic "
                  "attack range = 2 x total bonus range (max 5). Art tag = category cost x total category tags. Precise "
                  "Attack = 10. Range +1 = 2 x total bonus range (max 5).")},
    ]


# ---------------------------------------------------------------------------------------------------------
def build(pdf, talents, enemies):
    items = rs.build(pdf)
    # locate section starts in the stream
    starts = []
    cursor = 0
    for entry in PLAN:
        if entry[0] == "g":
            continue
        marker = entry[3] if entry[0] == "s" else entry[2]
        idx = None
        for i in range(cursor, len(items)):
            if items[i]["kind"] in ("p", "x") and items[i]["text"].startswith(marker):
                idx = i
                break
        if idx is None:
            raise SystemExit("marker not found after item %d: %r" % (cursor, marker))
        starts.append((entry, idx))
        cursor = idx + 1
    spans = {}
    for n, (entry, idx) in enumerate(starts):
        end = starts[n + 1][1] if n + 1 < len(starts) else len(items)
        spans[id(entry)] = (idx, end)

    def text_of(idx, end):
        paras = [it["text"] for it in items[idx:end] if it["kind"] in ("p", "x")]
        return "\n\n".join(paras)

    intros = {}
    for entry, idx in starts:
        if entry[0] == "i":
            a, b = spans[id(entry)]
            intros[entry[1]] = text_of(a, b)
    gens = talent_group_sections(talents, intros)
    gens["bestiary"] = bestiary_sections(enemies)
    gens["glossary"] = glossary_sections(pdf)
    gens["quickref"] = [dict(chapter=CH[10], **q) for q in QUICKREF]
    gens["reference_tables"] = reference_table_sections()

    sections = []
    for entry in PLAN:
        if entry[0] == "i":
            continue
        if entry[0] == "g":
            key = entry[2]
            if key in ("glossary",):
                sections.extend(gens[key])
            elif key == "quickref":
                # reference tables come before the quick-reference sheets
                sections.extend(gens["reference_tables"])
                sections.extend(gens[key])
            elif key == "reference_tables":
                continue
            else:
                sections.extend(gens[key])
            continue
        a, b = spans[id(entry)]
        text = text_of(a, b)
        page = items[a]["page"]
        sections.append({"chapter": CH[entry[1]], "title": entry[2], "page": page, "text": text})
    used_ids = set()
    for s in sections:
        base = slug(s["title"])[:70]
        sid, n = base, 2
        while sid in used_ids:
            sid = "%s_%d" % (base, n)
            n += 1
        used_ids.add(sid)
        s["id"] = sid
    out = []
    for s in sections:
        out.append({"id": s["id"], "chapter": s["chapter"], "title": s["title"], "page": s["page"], "text": s["text"]})
    return out
