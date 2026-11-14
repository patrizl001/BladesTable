# Blades Table

A local virtual table for playing **Blades of Ether** solo, with Claude as the Architect (GM).

* A small daemon keeps all game state: character sheets, dice, bond points, the combat grid, cooldowns,
  special dice, statuses, journal, NPCs, session recaps.
* Claude runs the game through an **MCP server** (45 tools): it creates the campaign, builds characters
  with you, rolls, runs combat, and writes things down so a new chat can pick the story back up.
* You watch a **live web page**: scene, sheets, battle map with Blade radii, dice tray, journal.
  Check difficulties, enemy stat cards and GM notes are not sent to that page.

Linux, Python 3.10+. No API key; it works with whatever Claude client you already use that speaks MCP.

## Install

```
git clone https://github.com/patrizl001/blades-table && cd blades-table
./install.sh           # makes .venv (uses uv if you have it, otherwise python3 -m venv + pip)
```

## Connect Claude

Pick one. Both talk to the same daemon, so you can switch freely.

**A. Local (stdio) MCP server** — for clients where you register a command, the same way you would any
other local MCP server:

* command: `/full/path/to/blades-table/boe.sh`
* args: `stdio`

The bridge starts the daemon by itself if it isn't running.

**B. HTTP** — start the daemon yourself and point the client at it:

```bash
./boe.sh serve --open                 # table at http://127.0.0.1:8765/
claude mcp add --transport http blades-table http://127.0.0.1:8765/mcp     # Claude Code
```

For Claude Code there is also `./boe.sh init-table ~/my-game`, which writes a play folder containing
`.mcp.json` and a `CLAUDE.md` that tells Claude it is the Architect; run `claude` inside that folder.

## Play

1. Open the table: http://127.0.0.1:8765/ (keep it beside the chat).
2. Tell Claude: *"You're the Architect for Blades of Ether. Call session_begin."* (There is also an MCP
   prompt named `architect` that says this.)
3. First time: Claude sets up the campaign and walks you through character creation. You play one of the
   Bearer/Blade pair; Claude plays your partner (or you can play both).
4. During play, say what your character does and how. In combat, name squares as `x,y` from the map.
5. When you stop, ask Claude to end the session. It writes a recap and awards bond points.
6. Next time, in a brand-new chat, step 2 again. The briefing restores everything.

Useful things to ask for: "undo that", "show me my sheet options for spending BP", "add a house rule: …",
"look up the rule for …".

## Commands

```
./boe.sh serve [--port N] [--open]   run the daemon (UI + MCP)
./boe.sh stdio                        stdio bridge (auto-starts the daemon)
./boe.sh status | stop
./boe.sh init-table <dir>
```

Environment: `BOE_PORT` (default 8765), `BOE_HOME` (default `~/.local/share/blades-table`). Campaigns
live in `$BOE_HOME/campaigns/<name>/campaign.json` with the last 40 undo snapshots; back up that folder
to back up a campaign.

## How it stays on the rails

* Claude gets a compact Architect guide plus the campaign state from `session_begin`, and can search the
  full rulebook (`rules_lookup`) and the 129-talent catalog (`talent_lookup`).
* The engine enforces creation budgets, BP costs, ranges, movement, radii, cooldowns, special dice and
  effect durations. Claude decides attributes, difficulty and what results mean. Any rule can be
  overridden deliberately (`force`, `combat_adjust`), and house rules are stored with the campaign.
* Talents with simple numeric effects are automatic (HP, initiative, movement, starting cooldowns, radius
  talents, Crisis Catalyst, Desperate Defense, Dirty Fighter, Protective Aegis, Final Flicker). The rest
  are applied by the Architect's ruling.
* Table rulings where the book is ambiguous are listed in the guide (`gm_guide("rulings")`), including the
  element/idea mapping erratum on the book's page 34.

## Development

`.venv/bin/pytest -q` runs 251 tests. `SPEC.md` is the original design and `ARCHITECTURE.md` describes the current code. `dev/` has the scripted playtest and UI
check scripts. `tools/extract_data.py <rulebook.pdf>` regenerates `boe/data/*.json`.

## Adapting it to other games

The engine, server, UI shell, journal and memory layer are game-agnostic; the rules, character creation,
combat and data are specific to Blades of Ether. `ARCHITECTURE.md` maps which is which and lists the steps
to port it to another system.

## Credits and licence

*Blades of Ether* is by Alexis Eva, Kaylee Maya and Ruby Soleil-Raine (gears.link/blades), released under
CC BY-NC-SA 4.0. The rules text and data in `boe/data/` are derived from that rulebook and are shared
under the same license (see `boe/data/NOTICE.md`); non-commercial use only. The rulebook itself is not
included. The license for the project's own code is MIT-licensed. This is an unofficial fan project
