"""CORE MCP tools. `register(mcp, engine)` is the entry point; COMBAT uses the same wrapper."""
from __future__ import annotations

import functools
import json
import sys
import traceback
from typing import Annotated, Any, Optional

from mcp_types import CallToolResult, TextContent
from pydantic import Field

from . import characters as ch
from . import reference, world
from .engine import Engine, GameError

SERVER_INSTRUCTIONS = (
    "You are the Architect for a solo Blades of Ether campaign. Call session_begin first. "
    "Never roll dice or track numbers yourself; use the tools. Use rules_lookup when unsure."
)

ARCHITECT_PROMPT = """You are the Architect (game master) for a solo campaign of the tabletop RPG "Blades of Ether", \
played with the Blades Table tools on this MCP server. The human is the player; you narrate the world, voice every NPC, \
judge outcomes, and let the engine do the dice and bookkeeping.

Start now: call `session_begin`. It returns the GM guide, the campaign recap, the party sheets and open threads. \
If it says there is no active campaign, ask the player what kind of story they want, then use `campaign_create`, \
`creation_options` and `character_create` to build the party. Never roll dice or track HP, cooldowns or BP in your head; \
use the tools (`roll_check`, `combat_*`, `character_advance`, ...). Use `rules_lookup` when unsure, and finish every \
session with `session_end`. The player watches the table (scene, sheets, dice, map) in the browser UI."""


def _compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def safe(fn):
    """Wrap a tool function: GameError/crash -> {"ok":false,"errors":[..]}; result -> compact JSON text."""

    @functools.wraps(fn)
    def inner(*a, **kw):
        try:
            res = fn(*a, **kw)
            if not isinstance(res, dict):
                res = {"ok": True, "result": res}
            res.setdefault("ok", True)
        except GameError as e:
            res = {"ok": False, "errors": [str(e)]}
        except Exception as e:  # never crash the server on bad tool input
            print(traceback.format_exc(), file=sys.stderr)
            res = {"ok": False, "errors": [f"internal error: {type(e).__name__}: {e}"]}
        return CallToolResult(content=[TextContent(type="text", text=_compact(res))])

    return inner


class SafeMCP:
    """Proxy over MCPServer whose `.tool()` wraps every tool with `safe` and plain-text output."""

    def __init__(self, mcp):
        self._mcp = mcp

    def __getattr__(self, name):
        return getattr(self._mcp, name)

    def tool(self, name=None, **kw):
        def deco(fn):
            self._mcp.add_tool(safe(fn), name=name or fn.__name__, structured_output=False,
                               **{k: v for k, v in kw.items() if k != "structured_output"})
            return fn
        return deco

    def add_tool(self, fn, name=None, **kw):
        kw.pop("structured_output", None)
        self._mcp.add_tool(safe(fn), name=name or fn.__name__, structured_output=False, **kw)


def as_safe(mcp) -> SafeMCP:
    return mcp if isinstance(mcp, SafeMCP) else SafeMCP(mcp)


def P(desc: str):
    return Field(description=desc)


Attr = "might|willpower|calculation|gut|experience|knowledge|stamina|empathy|attunement|swiftness|improvisation|passion"


def register(mcp, engine: Engine) -> None:
    mcp = as_safe(mcp)
    tool = mcp.tool

    # ----------------------------------------------------------- campaigns
    @tool(description="List saved campaigns (slug, name, session/arc, characters) and which one is active.")
    def campaign_list() -> dict:
        return world.campaign_list(engine)

    @tool(description="Create a new campaign and make it active. starting_point sets the character-creation "
                      "budgets for everyone: fresh_face (8 attribute points, 2 field skills, 2 tags/art, 5 talent "
                      "ranks), part_time_hero (16/3/4/8), veteran (24/4/6/11), titan_savior (32/5/8/14). "
                      "Afterwards create characters with character_create, then call session_begin.")
    def campaign_create(
        name: Annotated[str, P("Campaign title")],
        starting_point: Annotated[str, P("fresh_face | part_time_hero | veteran | titan_savior")],
        premise: Annotated[str, P("One or two sentences: the setup/hook")] = "",
        tone: Annotated[str, P("Tone/genre notes, e.g. 'hopeful swashbuckling, found family'")] = "",
        safety: Annotated[list[str], P("Lines/veils/topics to avoid or fade out (safety tools)")] = [],
        player_name: Annotated[str, P("The human player's name")] = "",
    ) -> dict:
        return world.campaign_create(engine, name, starting_point, premise, tone, safety, player_name)

    @tool(description="Switch the active campaign to an existing saved one (see campaign_list). Then call session_begin.")
    def campaign_load(slug: Annotated[str, P("Campaign slug from campaign_list")]) -> dict:
        return world.campaign_load(engine, slug)

    @tool(description="Rename the active campaign's title. Safe at any time, even mid-session or mid-combat: "
                      "characters, bonds, BP, entities, journal, rolls, recaps, combat and undo history are "
                      "untouched, and the rename is logged as a system journal entry (older journal text that "
                      "mentions the old title is deliberately left as written). The save folder keeps its name "
                      "unless rename_folder=true, which also renames it to match the new title. Undo can revert "
                      "the title but never moves the folder back.")
    def campaign_rename(
        name: Annotated[str, P("New campaign title (max 80 characters)")],
        rename_folder: Annotated[bool, P("Also rename the save folder (the slug shown by campaign_list) "
                                         "to match; normally unnecessary")] = False,
    ) -> dict:
        return world.campaign_rename(engine, name, rename_folder)

    @tool(description="Record a house rule / table ruling for this campaign. It is shown in every future "
                      "session_begin briefing. Use for rulebook modifications you and the player agree on.")
    def house_rule_add(text: Annotated[str, P("The rule, stated concisely")]) -> dict:
        return world.house_rule_add(engine, text)

    # ------------------------------------------------------------ sessions
    @tool(description="CALL THIS FIRST in every conversation. Opens a session if none is open (increments the "
                      "session counter, refreshes per-session talents) and returns the full briefing: GM guide "
                      "core sections, campaign premise/tone/safety/house rules, the last two recaps, arc info, the "
                      "current scene, compact party sheets, bonds and affinities, open threads, world entities, any "
                      "active combat, and the UI URL. Idempotent: calling it again while a session is open "
                      "returns the briefing again without a new session.")
    def session_begin() -> dict:
        return world.session_begin(engine)

    @tool(description="Close the session: writes the recap and awards Bond Points. Every attended PC gets +1 BP; "
                      "each pair in bond_awards (bonds meaningfully explored or changed this session) gives both "
                      "characters +1, and +1 more each if they are partners (a Bearer with two Blades gets the "
                      "partner bonus only once). Optionally rewrite bonds and shift affinities. Players spend BP "
                      "between sessions with character_advance.")
    def session_end(
        summary: Annotated[str, P("Recap of the session (3-6 sentences, no secrets: the player sees it)")],
        bond_awards: Annotated[list[dict[str, Any]], P("[{a:'<char>', b:'<char>', reason:'...'}] one per bond played to")] = [],
        bond_updates: Annotated[list[dict[str, Any]], P("[{from, to, name, benefit, drawback}] rewritten bonds (omitted fields keep their value)")] = [],
        affinity_changes: Annotated[list[dict[str, Any]], P("[{a, b, delta | value, reason}] affinity shifts (-2..2)")] = [],
        attended: Annotated[Optional[list[str]], P("Character ids/names that attended; default all living characters")] = None,
    ) -> dict:
        return world.session_end(engine, summary, bond_awards, bond_updates, affinity_changes, attended)

    @tool(description="End the current story arc (typically 3-6 sessions): archives the arc, refreshes every "
                      "character's once-per-arc abilities (I'm Really Feeling It, It's Reyn Time, The Heronop "
                      "Special) and per-arc talents, grants each PC one art-tag refund, and starts the next arc. "
                      "Call session_end first.")
    def arc_end(
        title: Annotated[str, P("Title of the arc that just ended")],
        summary: Annotated[str, P("What the arc accomplished/changed")],
        next_arc_title: Annotated[str, P("Working title of the next arc (optional)")] = "",
    ) -> dict:
        return world.arc_end(engine, title, summary, next_arc_title)

    @tool(description="Read game state. scope: 'summary' (default, tiny), 'party' (compact sheets, teams, affinity), "
                      "'character:<id>' (one full sheet), 'world' (entity list), 'journal:<n>' (last n entries), "
                      "'combat' (same as combat_state), 'full' (everything; large, avoid).")
    def get_state(scope: Annotated[str, P("summary | party | character:<id> | world | journal:<n> | combat | full")] = "summary") -> dict:
        return world.get_state(engine, scope)

    # ----------------------------------------------------------- reference
    @tool(description="Read the Architect's guide for running this table. With no topic returns the list of section "
                      "titles; with a topic (title or part of a title, case-insensitive) returns that section.")
    def gm_guide(topic: Annotated[str, P("Section title or substring; empty lists sections")] = "") -> dict:
        return reference.gm_guide(topic)

    @tool(description="Search the Blades of Ether rulebook. Returns the best-matching rulebook sections (title, page, "
                      "text). Use whenever you are unsure of a rule. Note: the book's p.34 element lists swap "
                      "truth/compassion; correct mapping: bravery=fire/water, truth=wind/ice, compassion=earth/"
                      "electricity, justice=light/dark.")
    def rules_lookup(query: Annotated[str, P("Keywords, e.g. 'toppled status' or 'special attack chain'")],
                     limit: Annotated[int, P("Max sections (1-8)")] = 3) -> dict:
        return reference.rules_lookup(query, limit)

    @tool(description="Look up talents from the catalog: rank, category, prerequisites, creation-only, usage limits "
                      "and rules text. Filter by keywords, category (universal|bearer|blade|pair|archetype|"
                      "archetype_talent) and role (bearer|blade).")
    def talent_lookup(query: Annotated[str, P("Name or keywords; empty lists the catalog")] = "",
                      category: Annotated[str, P("Optional category filter")] = "",
                      role: Annotated[str, P("Optional role filter: bearer | blade")] = "") -> dict:
        return reference.talent_lookup(query, category, role)

    @tool(description="Character-creation cheat sheet for this campaign's starting point: attribute/field-skill/"
                      "art-tag/talent budgets, the art tag table with costs and limits, the talent list for a role, "
                      "and an example sheet for character_create.")
    def creation_options(role: Annotated[str, P("bearer | blade | empty for both")] = "") -> dict:
        return ch.creation_options(engine, role)

    # ---------------------------------------------------------- characters
    @tool(description="Create a player character (Bearer or Blade) from a sheet, validated against the campaign's "
                      "starting point (attribute points, field skills, art tags per art/category/role/affinity, "
                      "talent ranks and prerequisites, one archetype). Fills defaults, derived traits, full HP, "
                      "Elemental Mastery, free potency on each art, teams (partner), and 0 affinity with the rest of "
                      "the party. sheet keys: name, role ('bearer'|'blade'), pronouns, weapon, home_titan, appearance, "
                      "personality, background, controller ('player'|'architect'), partner (name or id; or partners "
                      "list), attributes {attribute: value} (unlisted = 1), affinities [one element], field_skills "
                      "[name | {name,description}], arts [3 x {name, description, tags}] where tags is a dict "
                      "{tag: count} or a list of tag names and is the art's FINAL tag set (free potency:1 included "
                      "automatically), e.g. {\"potency\":2,\"cooldown\":1,\"break\":1,\"side\":1} (one distinct tag per "
                      "category except fundamentals; creation_options has the tag table), talents [name | {name|id, rank, choice}], bonds {other: {name, benefit, "
                      "drawback}}. On rule violations returns ok:false with every problem; with force=true applies "
                      "anyway and records a warning.")
    def character_create(sheet: Annotated[dict[str, Any], P("The character sheet (see description)")],
                         force: Annotated[bool, P("Apply despite rule violations (GM override)")] = False) -> dict:
        return ch.character_create(engine, sheet, force)

    @tool(description="Free-form GM patch of a character: narrative fields (name, pronouns, weapon, appearance, "
                      "personality, background, notes), controller, hp, hp_delta, dead, inventory (replace), "
                      "inventory_add/inventory_remove (lists), and, by GM fiat, attributes (merged), bp {current,total}, "
                      "arc_abilities, bonds, affinities, field_skills, arts, talents, basic_range_bonus, "
                      "partner_ids, tag_refund_available. Derived traits are recomputed. Does not charge BP: use "
                      "character_advance for purchases.")
    def character_update(char_id: Annotated[str, P("Character id or name")],
                         patch: Annotated[dict[str, Any], P("Fields to change")]) -> dict:
        return ch.character_update(engine, char_id, patch)

    @tool(description="Spend Bond Points. purchase.type: 'attribute' {attribute} (2 x new rank, one rank at a time); "
                      "'affinity' {element} (7 x new total); 'field_skill' {name, description} (3); 'talent' {talent, "
                      "rank?, choice?} (3 x rank; upgrading an upgradable talent costs 3 per added rank; prerequisites "
                      "and creation-only enforced); 'basic_range' {} (2 x new bonus, max +5); 'art_tag' {art, tag} "
                      "(category cost x tags in that category after purchase, counting the free potency; range 2 x new "
                      "bonus; precise 10); 'refund_tag' {art, tag} (once per arc after arc_end: regain the cost of the "
                      "most recent tag in that category); 'rename_art' {art, name, description} (free). art is the "
                      "0-based index or the art's name. Optional purchase.cost overrides the price (GM fiat). Returns "
                      "the cost and remaining BP. force=true overrides rule violations including insufficient BP.")
    def character_advance(char_id: Annotated[str, P("Character id or name")],
                          purchase: Annotated[dict[str, Any], P("{type: ..., ...} see description")],
                          force: Annotated[bool, P("Override rule violations / insufficient BP")] = False) -> dict:
        return ch.character_advance(engine, char_id, purchase, force)

    @tool(description="Define or rewrite one character's bond toward another (name, benefit, drawback). Bonds are "
                      "directional (each side writes their own); affinity is shared (see affinity_set).")
    def bond_set(from_id: Annotated[str, P("Character whose bond this is")],
                 to_id: Annotated[str, P("Character the bond is toward")],
                 name: Annotated[str, P("Short descriptor, e.g. 'Rival'")],
                 benefit: Annotated[str, P("How the bond makes them stronger")] = "",
                 drawback: Annotated[str, P("How the bond causes trouble")] = "") -> dict:
        return ch.bond_set(engine, from_id, to_id, name, benefit, drawback)

    @tool(description="Set or shift the shared affinity (-2..+2) between two characters. Use value for absolute, delta "
                      "for relative. Affinity is the dice-pool modifier when one helps the other (roll_check helper_id).")
    def affinity_set(a: Annotated[str, P("First character")], b: Annotated[str, P("Second character")],
                     value: Annotated[Optional[int], P("New absolute value")] = None,
                     delta: Annotated[Optional[int], P("Relative change")] = None,
                     reason: Annotated[str, P("Why (logged)")] = "") -> dict:
        return ch.affinity_set(engine, a, b, value, delta, reason)

    @tool(description="Grant (or remove, with a negative amount) Bond Points outside the normal session_end awards.")
    def grant_bp(char_ids: Annotated[list[str], P("Characters to grant to")],
                 amount: Annotated[int, P("BP to add")],
                 reason: Annotated[str, P("Why (logged)")] = "") -> dict:
        return ch.grant_bp(engine, char_ids, amount, reason)

    # --------------------------------------------------------------- dice
    @tool(description="THE general-purpose roll: you choose the attribute that fits HOW the character acts (any attribute "
                      "can fit if the player explains why) and the check. Pool = attribute + modifiers; each 5-6 is a "
                      "success; net = successes - check; net>=2 success, 1 near_hit (succeeds with a complication "
                      "you introduce), 0 near_miss (fails but you offer a benefit), <0 failure. Check 0 is typical "
                      "(need one success); it is secret from the player. helper_id adds the pair's shared affinity as a "
                      "modifier when an ally helps. use='reyn_time' guarantees success (once per arc); use='heronop' "
                      "turns this character's previous failed check into a near miss without rolling (once per arc). "
                      "Only roll when failure would be interesting. Field skills and talents are your judgment: add "
                      "dice via modifier. Requires an open session.")
    def roll_check(char_id: Annotated[str, P("Character id or name")],
                   attribute: Annotated[str, P(Attr + " (not needed for use='heronop')")] = "",
                   label: Annotated[str, P("What is being attempted (shown to the player)")] = "",
                   check: Annotated[int, P("Difficulty: successes to meet (secret). 0 = one success needed")] = 0,
                   modifier: Annotated[int, P("Dice added/removed (field skill +2, hindrance -1, ...)")] = 0,
                   modifier_notes: Annotated[str, P("Reason for the modifier")] = "",
                   helper_id: Annotated[Optional[str], P("Ally helping: adds your shared affinity to the pool")] = None,
                   extra_attributes: Annotated[list[str], P("Extra attributes whose full values are added (special rules only)")] = [],
                   use: Annotated[Optional[str], P("null | 'reyn_time' | 'heronop'")] = None,
                   force: Annotated[bool, P("Roll outside a session / re-use a spent ability")] = False) -> dict:
        return ch.roll_check(engine, char_id, attribute, label, check, modifier, modifier_notes, helper_id,
                             extra_attributes, use, force)

    @tool(description="Roll a raw pool of d6 (successes on 5-6) for opposed GM rolls or anything not tied to a "
                      "character. Opposed check rule: whoever rolls more successes gets what they intended; ties are "
                      "near misses for both.")
    def roll_dice(n: Annotated[int, P("Number of d6")], label: Annotated[str, P("What the roll is for")] = "",
                  who: Annotated[str, P("Roller name")] = "Architect") -> dict:
        return ch.roll_dice(engine, n, label, who)

    @tool(description="Out-of-combat reconciliation burst: two characters with NEGATIVE affinity set aside their "
                      "differences to tackle a challenge. At -1 each contributes ONE attribute to the pool; at -2 each "
                      "contributes TWO. Rolls the combined pool and resets their affinity to 0. (In combat use "
                      "combat_special with free_burst=true.)")
    def reconciliation_burst(a: Annotated[str, P("First character")], b: Annotated[str, P("Second character")],
                             attributes_a: Annotated[list[str], P("Attributes from a (1 at -1 affinity, 2 at -2)")] = [],
                             attributes_b: Annotated[list[str], P("Attributes from b")] = [],
                             label: Annotated[str, P("The challenge")] = "",
                             check: Annotated[int, P("Check (secret difficulty)")] = 0,
                             modifier: Annotated[int, P("Extra dice")] = 0,
                             modifier_notes: Annotated[str, P("Reason for modifier")] = "",
                             mode: Annotated[str, P("'check' (only mode here)")] = "check",
                             force: Annotated[bool, P("Allow without a session / without negative affinity")] = False) -> dict:
        return ch.reconciliation_burst(engine, a, b, mode, attributes_a, attributes_b, label, check, modifier,
                                       modifier_notes, force)

    @tool(description="Mark an arc ability (feeling_it, reyn_time, heronop) or a limited-use talent (per arc/session/"
                      "combat) as used; undo_use=true marks it available again.")
    def use_ability(char_id: Annotated[str, P("Character id or name")],
                    ability: Annotated[str, P("feeling_it | reyn_time | heronop | talent name")],
                    undo_use: Annotated[bool, P("Restore instead of spend")] = False) -> dict:
        return ch.use_ability(engine, char_id, ability, undo_use)

    # ------------------------------------------------------------- world
    @tool(description="Set the current scene shown on the player's table UI (title, location, description, who is "
                      "present, mood). Call whenever the scene changes. The player sees all of this.")
    def scene_set(title: Annotated[str, P("Scene title")], location: Annotated[str, P("Where")] = "",
                  description: Annotated[str, P("Short player-facing description")] = "",
                  present: Annotated[list[str], P("Names of characters/NPCs present")] = [],
                  mood: Annotated[str, P("Mood/atmosphere")] = "") -> dict:
        return world.scene_set(engine, title, location, description, present, mood)

    @tool(description="Create or update (matched by name) a world entity: npc, location, titan, faction, thread (open "
                      "plot thread; shown in every briefing until status is closed/resolved), item, secret, other. "
                      "Only provided fields change on an existing entity. gm_only=true hides it from the player's UI "
                      "(secrets are always hidden); gm_notes are never shown to the player. card = an NPC stat card "
                      "{role, attack{dis,normal,adv}, defense{...}, hp, movement, initiative, range (reach in squares, "
                      "default 1), affinities, "
                      "best_attributes, art_tags, special_abilities[{name,text}], notes} or a bestiary id; NPC cards "
                      "are secret and used by combat tools.")
    def entity_upsert(kind: Annotated[str, P("npc | location | titan | faction | thread | item | secret | other")],
                      name: Annotated[str, P("Entity name (unique key)")],
                      summary: Annotated[Optional[str], P("One-line player-safe summary")] = None,
                      details: Annotated[Optional[str], P("Longer player-safe notes")] = None,
                      tags: Annotated[Optional[list[str]], P("Tags")] = None,
                      status: Annotated[Optional[str], P("e.g. 'ally', 'hunting the party', 'resolved'")] = None,
                      gm_only: Annotated[Optional[bool], P("Hide from the player UI")] = None,
                      gm_notes: Annotated[Optional[str], P("Secret GM notes")] = None,
                      card: Annotated[Any, P("NPC card object or bestiary id")] = None) -> dict:
        return world.entity_upsert(engine, kind, name, summary, details, tags, status, gm_only, gm_notes, card)

    @tool(description="Fetch one entity (full record including gm notes and card) by name or id.")
    def entity_get(name_or_id: Annotated[str, P("Entity name or id")]) -> dict:
        return world.entity_get(engine, name_or_id)

    @tool(description="List entities (id, kind, name, status, short summary), optionally one kind.")
    def entity_list(kind: Annotated[str, P("Filter by kind, or empty")] = "",
                    include_gm: Annotated[bool, P("Include gm_only entities")] = True) -> dict:
        return world.entity_list(engine, kind, include_gm)

    @tool(description="Delete an entity by name or id.")
    def entity_delete(name_or_id: Annotated[str, P("Entity name or id")]) -> dict:
        return world.entity_delete(engine, name_or_id)

    @tool(description="Add a journal entry (campaign log). kind: event (shown to the player), note, recap, system, bp. "
                      "gm_only=true keeps it out of the player's UI. Log important events, promises and discoveries so "
                      "a future conversation can recall them.")
    def journal_add(text: Annotated[str, P("The entry")], kind: Annotated[str, P("event | note | recap | system | bp")] = "event",
                    tags: Annotated[list[str], P("Tags")] = [],
                    gm_only: Annotated[bool, P("Hide from the player UI")] = False) -> dict:
        return world.journal_add(engine, text, kind, tags, gm_only)

    @tool(description="Keyword search across the journal, entities, session recaps and arc summaries: what happened "
                      "with X? Returns the most relevant results, preferring recent ones on ties.")
    def recall(query: Annotated[str, P("Keywords")], limit: Annotated[int, P("Max results")] = 8) -> dict:
        return world.recall(engine, query, limit)

    @tool(description="Undo the last N mutations (dice rolls included, so re-rolling after an undo gives new dice). "
                      "Nothing needs to be permanent. Up to 40 steps are kept. Returns what was undone.")
    def undo(steps: Annotated[int, P("How many mutations to undo")] = 1) -> dict:
        return world.undo(engine, steps)

    @mcp.prompt(name="architect",
                description="Start playing: makes Claude the Architect of a Blades of Ether campaign and calls session_begin.")
    def architect() -> str:
        return ARCHITECT_PROMPT
