# Architecture

Blades Table is a single local process that keeps a TTRPG campaign's state and exposes it two ways:
to an AI game master over **MCP**, and to the player as a read-only **web page**. The AI is the judge and
narrator; the engine is the bookkeeper and the dice. `SPEC.md` is the original design document; where it
and this file disagree, this file and the code win (see "Drift from SPEC.md" at the end).

```
 Claude (MCP client) ──HTTP /mcp──┐
 stdio-only clients ─ boe stdio ──┤         ┌── tools_core / tools_combat (thin wrappers)
                                  ▼         ▼
                              server.py ─ world / characters / combat   (pure game logic: fn(engine, ...) -> dict)
 browser ◄── /api/state, /api/events (SSE) ─┘         │
                                                      ▼
                                   engine.py: state dict, txn(), undo ring, atomic save, subscribers
                                                      │
                                   ~/.local/share/blades-table/campaigns/<slug>/campaign.json (+ undo/NNNN.json)
```

## Module map

"G" = reusable for any game; "S" = specific to Blades of Ether.

| File | Role | |
|---|---|---|
| `boe/engine.py` | `Engine`: the one mutable state dict, `txn(label)` (atomic, nestable, rolls back on exception, writes an undo snapshot, bumps `version`, notifies SSE), `undo`, campaign create/load/rename, `record_roll`, `log` (journal), `GameError` | G |
| `boe/dice.py` | seedable `Roller` (with `queue()` for deterministic tests), success counting, outcome tiers | mostly G (5-6 = success, near hit / near miss are the game's rule) |
| `boe/server.py` | Starlette app: static UI, `/api/state` (player view; `?view=gm` unredacted), `/api/events` (SSE), `/api/health`, MCP streamable-HTTP at `/mcp` with host-header protection | G |
| `boe/cli.py` | `boe serve / stdio / status / stop / init-table`; the stdio bridge proxies MCP to the daemon (starting it if needed) so any number of clients share one state | G (the text it writes into `CLAUDE.md` is S) |
| `boe/tools_core.py` | MCP tool registration for campaigns, sessions, characters, rolls, entities, journal; `as_safe` wrapper turns `GameError`/crashes into `{"ok": false, "errors": [...]}` | G wrapper, S tool set |
| `boe/world.py` | campaigns, sessions/arcs, scene, entities, journal, `recall`, the `session_begin` briefing | mostly G |
| `boe/views.py` | player-view redaction: strips `gm_only` entries, `gm_notes`, NPC cards, hidden check values, NPC HP | G idea, S field names |
| `boe/reference.py` | rulebook search (`rules_lookup`), talent catalog lookup | G pattern, S data |
| `boe/rules.py` | constants (attributes, ideas, elements, art tags, starting points, BP costs), derived stats | S |
| `boe/characters.py` | character creation validation, BP spending/refunds, bonds/affinity, roll helpers | S |
| `boe/combat.py`, `boe/tools_combat.py` | grid combat: initiative, movement and Blade radii, attacks/arts/specials, statuses, life-force sharing, ASCII map and turn context, GM fiat ops | S |
| `boe/data/` | `rules_sections.json`, `talents.json`, `bestiary.json`, `examples.json`, `gm_guide.md` (CC BY-NC-SA, see `NOTICE.md`) | S |
| `boe/web/` | single-page UI (plain HTML/CSS/JS, no build, no external requests). Generic: scene, journal, codex, dice tray. Specific: sheet layout, battle map, special dice | mixed |
| `tools/` | regenerates `boe/data/*.json` from the rulebook PDF (you must supply the PDF) | S |
| `tests/`, `dev/` | pytest suite; scripted playtests and UI checks (see `dev/README.md`) | |

## Conventions worth knowing

* **One mutation path.** Anything that changes the campaign runs inside `with engine.txn("label"):`. That
  gives atomic saves, undo and the live UI update for free. Nested `txn`s join the outer one.
* **Logic is separate from MCP.** Game logic lives in plain functions (`world.py`, `characters.py`,
  `combat.py`) taking `engine` first and returning a dict with `"ok"`. `tools_*.py` only declare parameters
  and descriptions. Tests call the functions directly; a few tests go through real MCP/HTTP.
* **The engine is authoritative for facts, the AI for judgment.** Dice, arithmetic, costs, positions and
  cooldowns come from tools. Which attribute applies, how hard something is, and what a result means are the
  AI's calls.
* **Rules never dead-end the GM.** Validating tools take `force`; without it a violation returns errors and
  changes nothing, with it the change applies and a warning is recorded. `combat_adjust` is the free-form
  fiat escape hatch.
* **Everything undoable.** Undo restores whole-state snapshots (including dice). It deliberately keeps the
  current folder slug, so undoing past a folder rename can't resurrect an old folder.
* **Player view vs GM view.** The browser only gets the redacted view. The AI sees everything via tools.
  Redaction lives in `views.py`; add a test whenever you add a field that could hold a secret.
* **Tool descriptions are the AI's manual.** Keep them accurate and short; the whole `tools/list` is about
  56k characters, which is a real context cost on every chat.

## State and persistence

One JSON document per campaign (`campaign.json`, schema in `SPEC.md` section 4 plus additions below), written
atomically (temp file + rename). The last 40 pre-mutation snapshots are kept in `undo/`. The active campaign
is named in `$BOE_HOME/active`. The folder name (slug) is authoritative over `meta.slug` inside the file.

## Adapting this to another TTRPG

There is no plugin interface yet; this is the route I would take, in order:

1. Copy the project, replace `boe/data/` with data for your game, and update `NOTICE.md`.
2. Rewrite `rules.py` (constants, derived stats) and `characters.py` (creation validation, advancement,
   rolls) for your system. The generic pieces they call are `engine.txn`, `record_roll`, `log` and
   `GameError`.
3. Decide whether your game has tactical combat. If not, delete `combat.py`/`tools_combat.py` and the map
   in `boe/web/`; `server.py` already tolerates `tools_combat` being absent. If it does, `combat.py` is a
   long worked example of the pattern.
4. Rewrite `gm_guide.md`. It is what a fresh AI reads at `session_begin`; the `## [core]` sections are sent
   in full, the rest on request via `gm_guide(topic)`.
5. Adjust the sheet and map widgets in the UI and the redaction rules in `views.py`.
6. A proper refactor would split `core/` (engine, server, cli, world, views, dice, tool wrapper) from
   `games/<system>/` (rules, characters, combat, data, guide, UI widgets) behind a small interface.

## Drift from SPEC.md

Additions since the spec was written: a `counters` key in state; `meta.former_names` and the
`campaign_rename` tool; `house_rule_add`; `combat_special_assign`; `get_state("combat")` as an alias; extra combat
fields (`pending_more`, `swap_lock`, per-combatant `start_applied`, `follow_opt`, `steam`); NPC cards accept an
optional `range`; `session_begin` also returns `recent_journal` (last 8 non-system entries); special-effect
durations from a split special use each target's damage share (SPEC said total successes).
