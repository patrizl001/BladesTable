# Blades Table — original design spec (see ARCHITECTURE.md for the current state)

A local "virtual table" for running **Blades of Ether** (the rulebook PDF is not
included in this repository; it is CC BY-NC-SA 4.0 from gears.link/blades) as a **solo campaign with
Claude as the Architect (GM)**.

## 1. Shape of the thing

One Python daemon (`boe serve`) owns all game state and exposes:

* **MCP server** (streamable HTTP at `/mcp`) — Claude drives everything through tools: dice, sheets,
  combat grid, journal, rules lookup. Claude is the judge; the engine is the bookkeeper and the dice.
* **Web UI** (`/`) — the player's view of the table: scene, character sheets, battle map, dice log,
  journal. Read-only, live-updated over SSE. Secrets (checks, enemy cards, GM notes) are never sent to it.
* **stdio bridge** (`boe stdio`) — for MCP clients that only spawn stdio servers (e.g. desktop app local
  servers). It must NOT own state: it ensures the daemon is running (spawns it detached if the port is
  dead), then proxies MCP stdio <-> the daemon's `/mcp`. Any number of bridges/clients may connect.

Principles:
1. **Engine is authoritative for facts** (dice, arithmetic, HP, cooldowns, positions, costs). Claude never
   does mental bookkeeping. Every mutating tool returns a compact digest of the new truth.
2. **Claude is authoritative for judgment** (which attribute, check difficulty, narrative outcome,
   whether a field skill applies). Rules validation never dead-ends the GM: every validating tool takes
   `force: bool = false`; on a violation without force it returns `{"ok": false, "errors": [...]}` and
   changes nothing; with force it applies and records a warning. (Rulebook p.75: rules are modifiable.)
3. **Context survives conversations.** A brand-new Claude chat must be able to call `session_begin` and be
   fully ready: rules primer, campaign recap, party sheets, open threads.
4. **Small tool results.** Tools return JSON text; keep it terse (no pretty giant dumps); include an ASCII
   map only where spatial reasoning is needed.
5. Everything is undoable (`undo`), because "nothing needs to be permanent" (p.68).

Stack: Python >= 3.10, `mcp` SDK **2.x** (installed: 2.3.0 — NOTE: `FastMCP` was renamed
`mcp.server.mcpserver.MCPServer`; read the installed package in `.venv/lib/python3.13/site-packages/mcp`
rather than trusting memory of 1.x), Starlette + uvicorn (already deps of mcp). Frontend: plain
HTML/CSS/JS, no build step, no CDN (must work offline). Venv already exists at `.venv` (use
`.venv/bin/python`, `.venv/bin/pytest`; add deps with `uv pip install --python .venv/bin/python X` only if
truly needed and record them in `pyproject.toml`).

Data dir: `$BOE_HOME` or `~/.local/share/blades-table/`; `campaigns/<slug>/campaign.json` (atomic write:
temp file + rename), `campaigns/<slug>/undo/NNNN.json` (ring of last 40 pre-mutation snapshots),
`active` file naming the active campaign slug. Default port 8765 (`BOE_PORT`), bind 127.0.0.1.

## 2. File ownership (do not edit files you don't own; report needed changes instead)

| Owner | Files |
|---|---|
| CORE | `pyproject.toml`, `boe/__init__.py`, `boe/cli.py`, `boe/__main__.py`, `boe/engine.py`, `boe/dice.py`, `boe/rules.py`, `boe/characters.py`, `boe/world.py`, `boe/reference.py`, `boe/views.py`, `boe/server.py`, `boe/tools_core.py`, `tests/test_core.py`, `install.sh`, `boe.sh` |
| COMBAT | `boe/combat.py`, `boe/tools_combat.py`, `tests/test_combat.py` |
| DATA | `boe/data/rules_sections.json`, `boe/data/talents.json`, `boe/data/bestiary.json`, `boe/data/examples.json`, `tools/extract_data.py`, `tests/test_data.py` |
| UI | `boe/web/index.html`, `boe/web/app.js`, `boe/web/style.css`, `dev/mock_state.json`, `dev/mock_server.py` |
| (lead) | `SPEC.md`, `boe/data/gm_guide.md`, `README.md` |

## 3. Constants (CORE puts these in `boe/rules.py`; everyone uses these exact ids)

```
IDEAS = {bravery:[might,willpower,calculation], truth:[gut,experience,knowledge],
         compassion:[stamina,empathy,attunement], justice:[swiftness,improvisation,passion]}
ELEMENT_IDEA = {fire:bravery, water:bravery, wind:truth, ice:truth,
                earth:compassion, electricity:compassion, light:justice, dark:justice}
```
(The book's p.34 list swaps truth/compassion elements; that is an erratum — p.9, the tag table and glossary
agree on the mapping above.)

Unique elemental effects (id -> element): `burning_blade`:fire, `arts_seal`:water, `blustering_gale`:wind,
`freezing_force`:ice, `cradling_earth`:earth, `electrifying_burst`:electricity, `blade_of_light`:light,
`shadow_manipulation`:dark.
Shared effects (tag id -> idea): `invigorating_steam`:bravery, `bitter_snowstorm`:truth,
`counter_spike`:compassion, `blinding_eclipse`:justice.

Art tags — an art's tags are a dict `tag_id -> count`:

| category (BP cat. cost / creation cost) | tag ids (max count) |
|---|---|
| fundamentals (3 / 1) | `potency`(5), `healing_potion`(1), `cooldown`(2) |
| aoe (15 / 3) | `circle`(2), `line`(1) |
| reactions (5 / 1) | `break`, `topple`, `launch`, `stagger` (1 each), `rush`(2) |
| positionals (3 / 1) | `side` (bearer only), `rear` (bearer only), `pincer` (blade only) |
| elemental (4 / 1, needs matching affinity) | `unique_effect`, `invigorating_steam`, `bitter_snowstorm`, `counter_spike`, `blinding_eclipse` |
| other | `range`(5; BP 2 x new bonus range; creation 1), `precise`(1; BP 10; creation counts as 2 tags) |

Rules: only **one distinct tag per category** except fundamentals (improvable tags may stack to their
max, e.g. `rush` x2, `circle` x2); `other` tags are uncategorized. BP cost of a categorized tag =
category cost x (number of tag instances in that category on that art after purchase). Every art starts
with free `potency`:1 (it counts as an existing fundamentals tag for later costs).

Starting points: fresh_face (8 attr pts, 2 field skills, 2 tags/art max 1 per cat, 5 talent ranks),
part_time_hero (16, 3, 4 tags max 2/cat, 8), veteran (24, 4, 6 tags max 2/cat, 11), titan_savior (32, 5,
8 tags max 3/cat, 14). Creation attribute cost per rank bought: ranks 2-4 cost 1, 5-8 cost 2, 9-12 cost 3;
all start at 1, max 12. An aoe tag counts as 3 creation tags, `precise` as 2. "max N per category" at
creation counts tag instances per category per art (the free potency is not counted against the budget).
Plus free field skill "Elemental Mastery", one elemental affinity, 3 arts.

BP costs: attribute 2 x new rank (one rank at a time); elemental affinity 7 x new total; field skill 3;
talent 3 x rank (upgradable talents: 3 per added rank); basic attack range 2 x new bonus (max bonus 5).
Tag refund (end of arc, one tag): refund = cost of the most recent tag in that category on that art.

Derived traits: max_hp = willpower + stamina + 4 (+talent bonuses: Indomitable +2, Fortified +4, Steel
Flesh +6, Living Amalgam choice "hp" +4); initiative_pool = max(improvisation+gut, calculation+experience)
(+3 First Strike, +3 Living Amalgam choice "initiative"); movement = 3 bearer (4 Quick Step, 5 Fleet of
Foot) / 1 blade radius-move (+1 Swift Slide, +1 Living Amalgam choice "radius"); basic_range = 1 + bonus;
max_radius = 3 (5 with Radius Master); start_cooldowns = [0,2,4] (Secondary Accelerator -> [0,0,4];
Prime Position -> [0,0,2]); ideas = sums. Untouched archetype: attunement = 0.

## 4. State schema (`campaign.json`) — the contract between all modules and the UI

```jsonc
{
 "schema": 1, "version": 0,                    // version increments on every committed mutation
 "meta": {"slug","name","created","starting_point","premise","tone","safety":[],"player_name","house_rules":[]},
 "clock": {"session":0,"session_open":false,"arc":1,"arc_title":"","combats":0},
 "scene": {"title":"","location":"","description":"","present":[],"mood":""},
 "characters": {"<char_id>": Character},
 "teams": {"<team_id>": {"id","bearer":"<char_id>","blades":["<char_id>"]}},
 "affinity": {"<idA>|<idB>": 0},             // ids sorted alphabetically, value -2..2, shared by the pair
 "entities": {"<ent_id>": {"id","kind":"npc|location|titan|faction|thread|item|secret|other","name",
              "summary","details","tags":[],"status":"","gm_only":false,"gm_notes":"","card":null|NpcCard,
              "updated_session":0}},
 "journal": [{"id","ts","session","arc","kind":"event|note|recap|system|bp","text","tags":[],"gm_only":false}],
 "rolls": [RollRecord],                         // newest last, keep last 200
 "combat": null | Combat,
 "sessions": [{"n","arc","started","ended","summary","bp_awards":[]}],
 "arcs": [{"n","title","summary","first_session","last_session"}]
}
```

Character:
```jsonc
{"id","name","pronouns","role":"bearer|blade","controller":"player|architect","team_id","partner_ids":[],
 "weapon","home_titan","appearance","personality","background",
 "attributes":{"might":1,...12 keys},
 "affinities":["fire"],
 "field_skills":[{"name","description"}],
 "basic_range_bonus":0,
 "arts":[{"name","description","tags":{"potency":1}}, x3],
 "talents":[{"id","name","rank","choice":"","per":null|"arc"|"session"|"combat"|"once","used":false}],
 "bp":{"current":0,"total":0},
 "arc_abilities":{"feeling_it":true,"reyn_time":true,"heronop":true},   // true = still available
 "bonds":{"<other_char_id>":{"name","benefit","drawback"}},
 "inventory":[], "notes":"", "dead":false, "tag_refund_available":false,
 "hp": 9,                                       // current, persists between combats
 "derived":{"max_hp","initiative_pool","movement","basic_range","max_radius","start_cooldowns":[0,2,4],
            "ideas":{"bravery":3,...}}          // CORE recomputes on every character change
}
```

NpcCard (rulebook p.72-74; NPCs never roll — values are results):
```jsonc
{"role":"bearer|blade|other","attack":{"dis":1,"normal":2,"adv":3},"defense":{"dis":0,"normal":1,"adv":2},
 "hp":5,"movement":3,"initiative":3,"affinities":[],"best_attributes":[],"art_tags":[],
 "special_abilities":[{"name","text"}],"notes":""}
```

RollRecord:
```jsonc
{"id","ts","session","who":"<name>","char_id":null,"label":"what is being attempted","kind":"check|attack|defense|initiative|special|raw",
 "attribute":"swiftness"|["swiftness","passion"]|null,"pool":5,"mods":[{"label":"Potency +1","value":1}],
 "dice":[5,3,2,4,6],"successes":2,"check":1,"net":1,
 "tier":"success|near_hit|near_miss|failure","auto":null|"reyn_time|heronop|topple|undodgeable",
 "damage":null|2,"note":""}
```
Tier: net >= 2 success; net == 1 near_hit (succeeds with complication); net == 0 near_miss (fails with a
benefit); net < 0 failure. `net = successes - check`. A success is a die showing 5 or 6. Pool < 1 -> roll 1
die and flag `"pool_floor": true` (failure also affects another character). For defense rolls vs an NPC
attack value A: record check = A, net = successes - A, and damage = max(0, A - successes) (so the
*attacker's* margin decides damage; defender net 0 = attack fails as attacker near miss; defender net -1 =
1 damage, attacker near hit).

Combat:
```jsonc
{"id","name","turns_taken":0,
 "map":{"name","width","height","cells":{"x,y":{"type":"wall|obstacle|hazard|difficult|feature|cover",
        "label":"","blocks_move":true,"blocks_sight":false,"note":""}}},     // origin top-left, x right, y down
 "combatants":{"<cid>":{
    "cid","name","short":"P1",                // 2-char map token
    "kind":"pc|npc","char_id":null,"side":"party|enemy|neutral","role":"bearer|blade|other",
    "team_id":null,"bearer_cid":null,"blade_cids":[],
    "pos":[x,y],"facing":"N|E|S|W","hp","max_hp","down":false,
    "statuses":[{"id","label","kind":"detrimental|beneficial","remaining":3,
                 "unit":"own_turns|until_source_turn_start|until_source_turn_end","source":"<cid>","data":{}}],
    "cooldowns":[0,2,4],                      // pc only; 0 = ready
    "turn":{"moved":0,"radius_moves":0,"acted":false,"attacked":false,"bonus_move":0,"dealt_damage":false,"swapped":false},
    "card":null|NpcCard,                      // npc only
    "combat_talents_used":[]
 }},
 "order":["<cid>",...],                        // order[0] is the current actor
 "pending_shifts":[{"cid","delta":1}],         // applied at end of current turn, after rotating
 "special":{"chain_level":0,"points":{"<team_id>":0}},   // chain_level = level of last special in the chain
 "pending":null|{"type":"special_split|life_force",...},
 "log":[{"turn","text"}]
}
```

## 5. Engine contract (CORE implements in `boe/engine.py`; COMBAT codes against it)

```python
class Engine:
    state: dict | None                 # active campaign state (schema above) or None
    roller: dice.Roller                # .roll(n) -> list[int]; Roller(seed=None) for tests; .queue([..]) to force dice in tests
    def txn(self, label: str):         # context manager: snapshot for undo, yields state dict, on clean exit
        ...                            #   bumps version, saves atomically, notifies UI subscribers; on exception restores
    def record_roll(self, **fields) -> dict   # fills id/ts/session, appends to state["rolls"], returns record
    def log(self, text, kind="event", tags=(), gm_only=False) -> dict   # journal entry
    def require_state(self) -> dict    # raises GameError("no active campaign") if none
class GameError(Exception): ...        # user-facing rule/usage error; tools convert to {"ok":false,"errors":[str]}
dice.count_successes(dice) ; dice.tier(net)
rules.recompute_derived(character)     # fills character["derived"]
rules.pair_key(a, b) -> "a|b"
```
`boe/tools_core.py` exposes `register(mcp, engine)`; `boe/tools_combat.py` exposes `register(mcp, engine)`;
`server.py` calls both. Tool functions are thin: parse args -> call pure functions in
`characters.py`/`world.py`/`combat.py` (signature style `fn(engine, ...) -> dict`) -> return dict. Keep all
game logic importable and testable without MCP. All tools return a dict with `"ok": true|false`.

## 6. MCP tools

Server `instructions` (short): "You are the Architect for a solo Blades of Ether campaign. Call
session_begin first. Never roll dice or track numbers yourself; use the tools. Use rules_lookup when unsure."

### CORE tools
* `campaign_list()`, `campaign_create(name, starting_point, premise="", tone="", safety=[], player_name="")`,
  `campaign_load(slug)`.
* `session_begin()` -> opens session (clock.session += 1 if not open), resets per-session talents, returns
  **the briefing**: gm_guide core sections, campaign meta, last 2 session recaps, arc info, scene, compact
  party sheets, affinity table, open threads, active NPC/location names, any active combat digest, UI URL.
  Idempotent while a session is open (returns the briefing again without incrementing).
* `session_end(summary, bond_awards=[{a,b,reason}], bond_updates=[{from,to,name,benefit,drawback}],
  affinity_changes=[{a,b,delta|value,reason}], attended=[char_ids default all])` -> each attended PC +1 BP;
  each awarded bond +1 BP to both, +1 more each if they are partners (a bearer with two blades gets that
  partner extra once per session); writes recap; closes session.
* `arc_end(title, summary, next_arc_title="")` -> resets arc_abilities and `per:"arc"` talents, sets
  `tag_refund_available` on every PC, clock.arc += 1.
* `get_state(scope="summary")` scope in summary | party | character:<id> | world | journal:<n> | full.
* `gm_guide(topic="")` -> list of section titles, or the named section of `boe/data/gm_guide.md`
  (sections split on `## `). `rules_lookup(query, limit=3)` -> ranked rulebook sections (title, page, text
  trimmed to ~2500 chars each) from `rules_sections.json`; simple BM25/keyword scoring, no deps.
  `talent_lookup(query="", category="", role="")` -> talents from `talents.json`.
  `creation_options(role)` -> budgets for the campaign's starting point, tag table, legal talents summary.
* `character_create(sheet: dict, force=false)` -> validates the whole sheet against the starting point
  (attribute points, field skill count, tags per art/category/role/affinity, talent ranks, prerequisites,
  creation-only, role restrictions, one archetype), fills defaults, derived, hp = max, team wiring
  (`partner_ids`), affinity 0 with every other PC. Returns sheet digest + `errors`/`warnings`.
  `character_update(char_id, patch: dict)` -> free-form GM patch of narrative fields, inventory, notes,
  controller, hp, and (GM fiat) anything else; recomputes derived.
* `character_advance(char_id, purchase: dict, force=false)` -> spend BP. purchase.type in attribute |
  affinity | field_skill | talent | basic_range | art_tag | refund_tag | rename_art. Returns cost, new BP.
* `bond_set(from_id, to_id, name, benefit, drawback)`, `affinity_set(a, b, value=None, delta=None, reason)`.
* `grant_bp(char_ids, amount, reason)`.
* `roll_check(char_id, attribute, label, check=0, modifier=0, modifier_notes="", helper_id=None,
  extra_attributes=[], use=None)` -> the general-purpose roll. `helper_id` adds the pair's affinity as a
  modifier (talent Building Through Conflict softens negatives). `use` in null | "reyn_time" (auto success:
  net = max(net, 2), mark used) | "heronop" (apply to the character's *previous* failed roll: convert it to a
  near miss) . Outside a session -> error unless force. Returns RollRecord + reminders (e.g. character's
  talents whose text mentions rolls of this kind — keep simple: list names of the character's non-combat
  talents).
* `roll_dice(n, label, who="Architect")` -> raw pool for opposed GM rolls.
* `reconciliation_burst(a, b, mode="check", ...)` -> out of combat: requires negative affinity; at -1 pool
  = one attribute from each; at -2 pool = both attributes from each (four attributes); rolls, sets affinity 0.
  (Combat version lives in combat tools via `combat_special(..., free_burst=true)`.)
* `use_ability(char_id, ability)` -> mark an arc ability or limited talent used/unused (`undo_use=true`).
* `scene_set(title, location="", description="", present=[], mood="")` (what the UI shows as the current scene).
* `entity_upsert(kind, name, summary="", details="", tags=[], status="", gm_only=false, gm_notes="", card=None)`,
  `entity_get(name_or_id)`, `entity_list(kind="", include_gm=true)`, `entity_delete`.
* `journal_add(text, kind="event", tags=[], gm_only=false)`, `recall(query, limit=8)` -> keyword search over
  journal + entities + session recaps (most relevant, then most recent).
* `undo(steps=1)` -> restores snapshots; returns what was undone.

### COMBAT tools
* `combat_start(name, map: {width,height,name?,cells?:[{x,y,type,label?,blocks_move?,blocks_sight?,note?}]},
  combatants: [{char_id | (name + card | bestiary:"<id>"), pos:[x,y], facing?, side?, bearer?: "<name of npc
  bearer for npc blades>", hp?}], feeling_it: [{char_id, attribute, reason}] = [],
  cooldown_order: {char_id:[art indices: ready, two, four]} = {}, ambush: null|"party"|"enemy" = null)`
  -> validates positions, rolls initiative for PCs (pool = derived.initiative_pool; ties -> larger pool
  first; NPC initiative is a static result), builds order (PC results are *team slots*: by default the
  member who rolled it takes it), sets cooldowns from derived.start_cooldowns in the given order, team
  special points 0 (+6 for each feeling_it), heals nothing. Returns turn context for the first actor.
* `combat_state(cid=None)` -> digest: ASCII map + legend, order, each combatant line (hp, statuses,
  cooldowns, radius for blades), team special dice, chain level, pending; with `cid` adds that actor's
  options: movement left, ready arts with computed range/pool modifiers, enemies in range per attack.
* `combat_move(cid, to:[x,y], forced=false, by=None, force=false)` -> Bearers/others: BFS orthogonal path
  length through passable, unoccupied cells <= movement budget (double if they have not attacked and
  declare `sprint`; simpler: allow up to 2x movement, and if moved > 1x then attacking this turn becomes
  illegal — track in turn.moved). Blades: destination must be in a radius reachable with remaining
  radius-moves (1/turn, 2 if not attacking; same lazy rule), any free cell of that radius; outside max
  radius: 1 square/turn. Bearer moving shifts the Blade's radius: return `blade_radius_change` info with
  the option (`combat_move` the blade to nearest square of old radius as a free reposition with
  `follow=true`) unless the bearer was moved against their will (`forced`). Radius n = Chebyshev distance
  n from the bearer (1 -> 3x3 ring+inside, 2 -> 5x5, 3 -> 7x7).
* `combat_attack(attacker, kind:"basic"|"art", art:int|None, target: cid | at:[x,y] | direction for line,
  attribute, label, modifier=0, modifier_notes="", defense:"normal"|"adv"|"dis"|int = "normal",
  effect: None|effect_id, effect_target: None|cid (for beneficial effects / heal recipient),
  heal_target=None, negate_positional=false, spare:[cids]=[] (precise), defender_attributes:{cid: attr} = {},
  force=false)` -> PC (or any roller) attacks. Range = Manhattan distance (diagonal counts 2); basic range =
  derived.basic_range; art range = 1 + range tag (aoe arts: base range 0 + range tag = how far the circle
  centre may be / extra line length; line = 5 + range squares in a cardinal direction; circle = 3x3, 5x5
  with circle x2). Line of sight: Bresenham; blocked by `blocks_sight` cells. Pool = attribute + potency
  + positional bonus (side +1 / rear +2 from target facing, checked before turning; pincer +2 if target is
  in a lower radius than the attacking Blade and blade within max radius) + modifier + status modifiers
  (blinding_eclipse -1, 3rd radius -1, outside max radius: half pool rounded up, Expeditionist variant)
  + auto talent bonuses that are purely numeric (Crisis Catalyst +2 at <= quarter HP; Dirty Fighter is +1
  damage vs toppled within 1 square). vs NPC: check = card.defense[level] (minus 1 if NPC has
  blinding_eclipse; toppled target: a failed attack becomes a 1-net near hit). vs PC target: defender rolls
  `defender_attributes[cid]` and check = defender successes. Damage = net if net >= 1. On hit apply in
  order: damage (+burning etc.), reactions (break / topple needs broken / launch needs broken: push net
  squares along attacker facing, collision damage = remaining squares, to both if a combatant is hit, order
  -1 if no terrain collision / stagger: order -1 / rush: bonus_move += count), elemental effect chosen via
  `effect` (must be allowed by the art's elemental tags + attacker affinities; `unique_effect` lets you
  pick any unique effect of an affinity you hold), healing_potion (heal_target +net HP, capped), special
  point (+1 to the team once per turn in which a basic attack or art dealt damage, max 18), facing updates
  (attacker faces target before; target faces attacker after), sets the art's cooldown to 6 - cooldown tag
  (even on a miss), marks turn.attacked. AoE: one attack roll compared against each target's defense; allies
  in the area are hit too unless `precise` and listed in `spare`; PCs in the area defend individually.
  Returns per-target results + RollRecord(s) + digest. If a Bearer PC would drop to <= 0 and their Blade can
  share life force, set `pending: life_force` instead of downing them and say so.
* `combat_npc_attack(attacker, targets:[cid] | at/shape for areas, level:"normal"|"adv"|"dis"|int,
  defender_attributes:{cid: attr}, defender_modifiers:{cid: int}={}, tags:[tag ids]=[], effect=None, label,
  ignore_range=false, force=false)` -> NPC static attack value vs each PC's defense roll (pool = attribute +
  modifiers: blustering_gale +1, blinding_eclipse -1, Desperate Defense +2 at <= quarter HP, radius
  penalties for blades). Damage = max(0, A - successes). Applies tags/effects on hit like above. NPC vs NPC:
  static vs static (attack - defense).
* `combat_special(attacker, level, ideas:{attacker: idea, partner?: idea}, effect, target | at:[x,y],
  label, free_burst=false, allocations=None)` -> validates level == chain_level + 1 (after 3 the chain
  resets to 0) and the team has `level` full dice (6 points each). Party-size rule: with exactly one PC team,
  dice are only consumed by a level 3 (all 18); two teams: normal cost and the *other* team gains 6 points
  after a level 2; three+: normal. L1: attacker rolls the idea's three attributes, single target. L2:
  attacker + partner both roll the same idea, damage split among chosen targets in a 3x3. L3: each rolls an
  idea of their choice, 5x5. Unopposed, undodgeable, infinite range, needs line of sight. Damage = total
  successes; effect from the idea(s) used regardless of affinity, duration from successes (cap 6). If more
  than one target and `allocations` missing -> store `pending: special_split` with the total and return;
  complete with `combat_special_assign(allocations:{cid: dmg})`. `free_burst` (reconciliation burst from
  negative affinity: -1 -> free L1 by the higher-idea partner, -2 -> free L3) costs nothing, ignores and does
  not change the chain, and resets the pair's affinity to 0. Specials do not grant special points.
* `combat_action(cid, label, attribute=None, check=0, modifier=0, kind="other"|"help_up"|"defend"|"heal", target=None, offensive=false)`
  -> a rolled non-attack action in combat (uses the action; `help_up` removes toppled from an adjacent ally
  without a roll; `heal` = Healer talent: unopposed art roll heals successes, engine applies the cooldown
  reset rule).
* `combat_end_turn(cid, facing=None, blade_pos=None)` -> must be the current actor (else error unless
  force). Ticks that actor's cooldown dice (-1 each, unless arts_seal), ticks own-turn statuses, expires
  "until source turn end" statuses, rotates order (actor to bottom), applies pending_shifts, then starts the
  next actor's turn: expire "until_source_turn_start" statuses they sourced, burning damage, toppled =>
  auto-skip note (`must_skip: true`), reset turn flags. Returns the next actor's turn context (same shape as
  `combat_state(cid)`), plus events that happened. Downed combatants are removed from `order`.
* `combat_swap_turn(cid)` -> current actor swaps this turn with their partner's next turn (once until every
  team member has taken a turn). `combat_delay(cid, places)` (talent Tactical Delay / GM fiat).
* `combat_life_force(blade, give:int | decline=true)` -> resolves `pending: life_force`: Bearer restored to
  `give` HP, Blade pays give + overkill... precisely: blade pays (damage needed to bring the bearer from its
  would-be HP to `give`) + 1 (Protective Aegis: no +1; Final Flicker: bearer to 1 HP for all blade HP).
  Declined/impossible -> Bearer and all their natural Blades are downed.
* `combat_adjust(ops:[{op, ...}], reason)` -> GM fiat batch. ops: damage{cid,n} heal{cid,n} set_hp
  status_add{cid,id,remaining,unit?,source?,data?} status_remove{cid,id} move{cid,to} face{cid,dir}
  shift_order{cid,delta} set_order{order} special_points{team_id,delta|value} cooldown{cid,art,value}
  add_combatant{...like combat_start entry} remove_combatant{cid} down{cid} revive{cid,hp}
  cell{x,y,type|null,...} chain_level{value} card{cid,patch}. This is the escape hatch for every talent and
  improvised effect the engine does not automate.
* `combat_end(outcome, summary="", restore_hp=true)` -> writes a journal event, copies HP back to
  characters (full restore if restore_hp), resets `per:"combat"` talents, clears state.combat, clock.combats += 1.

Status rulings (durations cap at 6; re-applying adds durations): `burning` own_turns, 1 dmg at start of
each of the target's turns; `arts_seal` target's next turn (own_turns 1): no arts, cooldowns frozen;
`blustering_gale` own_turns N (+1 defense); `frozen` until source's next turn starts (no movement; blade
frozen: cannot move at all); `cradled` until source's next turn starts (cleanse now + immune to detrimental);
`electrifying_burst` instant (target order -1, or chosen ally +1); `blade_of_light` non-blade: own_turns N,
+2 range; blade: own_turns 1 free radius movement without penalties; `shadowed` own_turns N (may only
attack `data.only_target`); `invigorating_steam` instant: chosen ally's chosen art cooldown -1 (if ready,
store `data.steam` so its next cooldown starts 1 lower); `snowstorm` own_turns N (-1 movement min 0, -1
attack ranges min 1); `counter_spike` on the attacker, own_turns N (anyone who successfully attacks them
takes 1); `blinded` until source's next turn *ends* (-1 attack and defense); `broken` until source's next
turn starts (re-apply: +1 full cycle); `toppled` through the target's next turn (cannot move or act; attacks
on them that would fail become 1-net near hits; removed by an adjacent ally's `help_up`). "Turn order -1"
means one place later.

## 7. HTTP API (CORE) for the UI

* `GET /` + static files from `boe/web/`.
* `GET /api/state` -> **player view** JSON: `{ok, version, has_campaign, meta, clock, scene, characters
  (full sheets), teams, affinity, entities (gm_only removed; gm_notes and card stripped), journal (gm_only
  removed, last 150), rolls (last 60; `check` and `net` removed unless kind is attack/defense/special where
  `damage` is shown), combat (NPC `card` removed, NPC hp replaced by `"condition":"fresh|scratched|hurt|
  badly hurt|down"` and hp/max_hp nulled; map/positions/statuses/order/special visible), sessions, arcs}`.
  `GET /api/state?view=gm` -> unredacted (for debugging; the UI hides it behind a "spoilers" toggle).
* `GET /api/events` -> SSE: `event: state` with `data: {"version":N}` on every commit, plus a comment
  heartbeat every 15 s. `GET /api/health` -> `{ok:true, name:"blades-table", version}`.
* `GET /api/campaigns` -> list. No write endpoints (the player talks to Claude; Claude uses MCP).

## 8. CLI (CORE)

`boe serve [--port] [--open]` (daemon; `--open` launches the browser via `xdg-open`), `boe stdio` (bridge;
never print to stdout except MCP frames; log to stderr / `$BOE_HOME/bridge.log`), `boe status`, `boe stop`,
`boe init-table <dir>` (writes a play folder: `.mcp.json` pointing at `http://127.0.0.1:8765/mcp` with
`"type":"http"`, and a `CLAUDE.md` telling Claude it is the Architect and to call `session_begin`).
`boe.sh` = wrapper that runs `.venv/bin/python -m boe "$@"` relative to its own location. `install.sh` =
creates `.venv` (uv if available, else `python3 -m venv` + pip), installs the package editable, prints next
steps. Pin `mcp>=2.3,<3`.

## 9. Definition of done for each module

Tests pass (`.venv/bin/pytest -q`), no network needed at runtime, no writes outside `$BOE_HOME`, and the
module's part of this spec is implemented or the deviation is listed in the agent's final report.
