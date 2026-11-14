"""COMBAT MCP tools: thin wrappers over boe.combat. `register(mcp, engine)` is the entry point."""
from __future__ import annotations

from typing import Annotated, Any, Optional, Union

from pydantic import Field

from . import combat as cm

try:
    from .tools_core import as_safe
except Exception:  # pragma: no cover - fallback keeps combat usable standalone
    import json

    def as_safe(mcp):
        class _S:
            def tool(self, name=None, **kw):
                def deco(fn):
                    def inner(*a, **k):
                        try:
                            res = fn(*a, **k)
                        except cm.GameError as e:
                            res = {"ok": False, "errors": [str(e)]}
                        except Exception as e:
                            res = {"ok": False, "errors": [f"internal error: {type(e).__name__}: {e}"]}
                        return json.dumps(res, default=str)
                    inner.__name__ = fn.__name__
                    inner.__doc__ = fn.__doc__
                    inner.__annotations__ = fn.__annotations__
                    mcp.add_tool(inner, name=name or fn.__name__, structured_output=False, **kw)
                    return fn
                return deco
        return _S()


def P(desc: str):
    return Field(description=desc)


ATTR = ("might|willpower|calculation|gut|experience|knowledge|stamina|empathy|attunement|swiftness|"
        "improvisation|passion")
EFFECTS = ("burning_blade(fire) arts_seal(water) blustering_gale(wind) freezing_force(ice) cradling_earth(earth) "
           "electrifying_burst(electricity) blade_of_light(light) shadow_manipulation(dark); shared: "
           "invigorating_steam bitter_snowstorm counter_spike blinding_eclipse")
RUN = (
    "HOW TO RUN COMBAT: combat_start -> read the returned turn context (map, order, actor options, reminders). "
    "On a PC's turn: combat_move (optional), then ONE action (combat_attack / combat_special / combat_action), "
    "move again if movement remains, then combat_end_turn(facing=...). On an NPC's turn use combat_npc_attack "
    "(NPCs never roll: you choose attack value level normal/adv/dis; players' PCs roll defense). "
    "Every result has a one-sentence `summary` to narrate from. Anything the engine does not automate: "
    "combat_adjust. When `suggest_end` appears, wrap up with combat_end. When the engine is waiting on you, results carry `pending` plus a `next` sentence naming the tool to call (combat_life_force / combat_special_assign); every other combat tool refuses until it is resolved."
)


def register(mcp, engine) -> None:
    tool = as_safe(mcp).tool

    @tool(description="Start a combat on a grid. " + RUN + " Rolls initiative for every PC (pool = derived "
          "initiative pool; NPC initiative is the static value on its card); ties go to the larger pool, PCs "
          "before NPCs. Rolled results are TEAM SLOTS: by default the member who rolled takes it "
          "(override with team_order). PCs start with HP from their sheet and cooldowns [ready, 2, 4] assigned "
          "to arts in cooldown_order. Positions are [x,y] with origin top-left, x right, y down; facing N = up. "
          "Returns the first actor's turn context.")
    def combat_start(
        name: Annotated[str, P("Name of the encounter")],
        map: Annotated[dict, P("{width, height, name?, cells?:[{x,y,type,label?,blocks_move?,blocks_sight?,note?}]}. "
                               "type: wall (blocks move+sight) | obstacle (blocks move) | cover (blocks move, not "
                               "sight) | hazard | difficult (cost 2) | feature. Keep maps small (<= ~12x12).")],
        combatants: Annotated[list[dict], P(
            "PC: {char_id, pos:[x,y], facing?, side?='party', hp?}. NPC: {name, card:{role,attack:{dis,normal,adv},"
            "defense:{dis,normal,adv},hp,movement,initiative,range?(default 1),affinities[],best_attributes[],art_tags[],"
            "special_abilities:[{name,text}],notes} OR bestiary:'<id>' (ids: pack_animal, elemental_ursine, novice_bearer, forgeling_blade, blade_eater, legendary_bearer, titanic_blade, rockbart), pos, facing?, side?='enemy'|'neutral', "
            "bearer?:'<name of the NPC Bearer>' (for NPC Blades), hp?}. Duplicate NPC names are auto-numbered "
            "('Arachno 1'); the cid is the slug (arachno_1).")],
        feeling_it: Annotated[list[dict], P("[{char_id, attribute, reason}] I'm Really Feeling It: adds that attribute "
                                           "to initiative and gives the team 6 special points (once per arc)")] = [],
        cooldown_order: Annotated[dict, P("{char_id: [art index starting ready, art index starting at 2, art index "
                                          "starting at 4]}; default [0,1,2]")] = {},
        ambush: Annotated[Optional[str], P("'party' or 'enemy': that side acts before the other side")] = None,
        team_order: Annotated[dict, P("{team_id: [char_ids in the order they take the team's slots, best slot first]}")] = {},
        force: Annotated[bool, P("Override rule violations (recorded as warnings)")] = False,
    ) -> dict:
        return cm.combat_start(engine, name, map, combatants, feeling_it, cooldown_order, ambush, team_order, force)

    @tool(description="Digest of the combat: ASCII map + legend, turn order, one line per combatant (hp, statuses, "
          "cooldowns, Blade radius), team special dice (e.g. '6,6,2'), special chain level, pending items. "
          "Pass cid (or 'current') to also get that actor's options: movement left, each attack option with range "
          "and which enemies are in range/line of sight, auto modifiers, reminders and (NPCs) the card.")
    def combat_state(cid: Annotated[Optional[str], P("Combatant cid, or 'current' for the acting combatant")] = None) -> dict:
        return cm.combat_state(engine, cid)

    @tool(description="Move a combatant. Bearers/NPCs: orthogonal path through free, passable squares, cost 1 per "
          "square (diagonal = 2, difficult terrain = 2); budget = Movement, doubled if they do not attack this "
          "turn (moving more than the base amount forbids attacking). Blades: `to` can be any free square; changing "
          "radius costs 1 radius-move per radius step (budget = Movement, doubled when not attacking); radius = "
          "Chebyshev distance to the Bearer (1=3x3, 2=5x5, 3=7x7); outside max radius a Blade moves 1 square/turn. "
          "When a Bearer moves, the result lists `blade_radius_change`: the Blade may stay or call "
          "combat_move(cid=<blade>, follow=true) to return to its previous radius (free). forced=true = moved "
          "against its will (no budget, no follow choice).")
    def combat_move(
        cid: Annotated[str, P("Who moves")],
        to: Annotated[Optional[list[int]], P("Destination [x,y] (omit with follow=true)")] = None,
        forced: Annotated[bool, P("Moved against their will (push, pull, GM fiat)")] = False,
        by: Annotated[Optional[str], P("Who/what moved them (flavour, with forced)")] = None,
        force: Annotated[bool, P("Override budget/turn/path violations")] = False,
        follow: Annotated[bool, P("Blade only: return to its previous radius after its Bearer moved")] = False,
    ) -> dict:
        return cm.combat_move(engine, cid, to, forced, by, force, follow)

    @tool(description="A PLAYER CHARACTER attacks (basic attack or art). The engine checks turn, cooldown, range "
          "(Manhattan; diagonal = 2), line of sight, builds the pool (attribute + potency + side/rear/pincer "
          "bonus + modifier + automatic modifiers), rolls, compares with the NPC's defense value (or has a PC target "
          "roll defense via defender_attributes), applies damage = net successes, reactions (break/topple/launch/"
          "stagger/rush), elemental effect, healing potion, special point (+1 per turn with damage), facing, and the "
          "art's cooldown. Pick `attribute` by the fiction (not just the highest). Area arts (circle/line) hit every "
          "combatant in the area including allies unless the art has `precise` and you list them in spare. "
          "Near hit (net 1) = hit with a complication you narrate; near miss (net 0) = miss with a benefit. "
          "Elemental effects (" + EFFECTS + "): pass effect=<id> when the art has unique_effect (arts with exactly one "
          "shared tag apply it automatically; effect='none' to skip).")
    def combat_attack(
        attacker: Annotated[str, P("cid of the attacking PC (must be the current actor)")],
        attribute: Annotated[str, P("Attribute rolled: " + ATTR)],
        kind: Annotated[str, P("'basic' or 'art'")] = "basic",
        art: Annotated[Optional[int], P("Art index 0-2 when kind='art'")] = None,
        target: Annotated[Optional[str], P("Target cid (single target; for circles it sets the centre)")] = None,
        at: Annotated[Optional[list[int]], P("[x,y] centre of a circle attack (distance <= art range)")] = None,
        direction: Annotated[Optional[str], P("N/E/S/W for line attacks")] = None,
        label: Annotated[str, P("Short description of the attack for the log")] = "",
        modifier: Annotated[int, P("Extra dice (+) or penalty (-) you judge applies")] = 0,
        modifier_notes: Annotated[str, P("Why the modifier")] = "",
        defense: Annotated[Union[str, int, dict], P("NPC defense used: 'normal'|'adv'|'dis'|integer, or {cid: level}")] = "normal",
        effect: Annotated[Optional[str], P("Elemental effect id to apply on hit (see description)")] = None,
        effect_target: Annotated[Optional[str], P("cid receiving beneficial effects / chosen ally for electrifying_burst/shadow_manipulation")] = None,
        heal_target: Annotated[Optional[str], P("cid healed by a healing_potion art (default attacker)")] = None,
        negate_positional: Annotated[bool, P("The target Bearer's Blade intercepts: drop the side/rear bonus and move that Blade between")] = False,
        spare: Annotated[list[str], P("cids spared by a precise area art")] = [],
        defender_attributes: Annotated[dict, P("{cid: attribute} each PC target defends with (required for PC targets)")] = {},
        defender_modifiers: Annotated[dict, P("{cid: int} extra defense dice you judge apply")] = {},
        effect_art: Annotated[Optional[int], P("Art index for invigorating_steam on effect_target")] = None,
        face: Annotated[Optional[str], P("Diagonal target: which cardinal the attacker faces (N/E/S/W)")] = None,
        force: Annotated[bool, P("Override rule violations (range, cooldown, turn order...)")] = False,
    ) -> dict:
        return cm.combat_attack(engine, attacker, kind, art, target, at, direction, attribute, label, modifier,
                                modifier_notes, defense, effect, effect_target, heal_target, negate_positional,
                                spare, defender_attributes, defender_modifiers, effect_art, face, force)

    @tool(description="An NPC attacks. NPCs never roll: you pick the attack value level ('normal'|'adv'|'dis' from "
          "the card, or an integer) according to the fiction. Each PC target rolls a defense pool (attribute from "
          "defender_attributes + automatic modifiers); damage = max(0, attack value - defense successes); NPC "
          "targets use their static defense (damage = attack - defense). Toppled targets take at least 1. tags = "
          "art tags this attack carries (break, topple, launch, stagger, rush, circle, line, range) and effect an "
          "elemental effect id (" + EFFECTS + "). Range is the card's `range` (default 1) + range tags unless "
          "ignore_range. Areas: shape 'circle'|'line' (or circle/line tags) with at=[x,y] or direction.")
    def combat_npc_attack(
        attacker: Annotated[str, P("NPC cid (must be the current actor)")],
        targets: Annotated[Optional[list[str]], P("Target cids (omit for area attacks)")] = None,
        level: Annotated[Union[str, int], P("'normal'|'adv'|'dis' or an integer attack value")] = "normal",
        defender_attributes: Annotated[dict, P("{pc cid: attribute they defend with}")] = {},
        defender_modifiers: Annotated[dict, P("{pc cid: int} extra defense dice you judge apply")] = {},
        tags: Annotated[list[str], P("Art tags this attack uses, e.g. ['break'] or ['circle','circle']")] = [],
        effect: Annotated[Optional[str], P("Elemental effect id")] = None,
        effect_target: Annotated[Optional[str], P("Beneficial-effect recipient / shadow target")] = None,
        label: Annotated[str, P("Short description")] = "",
        ignore_range: Annotated[bool, P("Ignore the attack range")] = False,
        at: Annotated[Optional[list[int]], P("Circle centre [x,y]")] = None,
        direction: Annotated[Optional[str], P("N/E/S/W for line attacks")] = None,
        shape: Annotated[Optional[str], P("'circle' or 'line' for area attacks")] = None,
        defense: Annotated[Union[str, int, dict], P("Defense level used against NPC targets")] = "normal",
        spare: Annotated[list[str], P("cids spared by a precise area attack")] = [],
        face: Annotated[Optional[str], P("Diagonal target facing choice")] = None,
        force: Annotated[bool, P("Override rule violations")] = False,
    ) -> dict:
        return cm.combat_npc_attack(engine, attacker, targets, level, defender_attributes, defender_modifiers,
                                    tags, effect, effect_target, label, ignore_range, at, direction, shape, defense,
                                    spare, face, force)

    @tool(description="Special attack (uses the action). Level must be chain level + 1 and the team needs level x 6 "
          "special points (dice: 1 point = a die showing 1, 6 = full). Unopposed, undodgeable, infinite range, needs "
          "line of sight. Pool = sum of the idea's three attributes (bravery: might+willpower+calculation; truth: "
          "gut+experience+knowledge; compassion: stamina+empathy+attunement; justice: swiftness+improvisation+"
          "passion). L1: attacker rolls one idea, one target. L2: attacker and partner both roll the same idea, "
          "damage split among targets in a 3x3 (at=[x,y]). L3: each rolls an idea of their choice, 5x5. Damage = "
          "total successes; the effect (one tied to the idea, any affinity) lasts as long as each target's share "
          "(max 6). One-team party: dice are only spent by level 3; two teams: level 2 gives the other team 6 "
          "points. If several targets and no allocations, the result is `pending: special_split`: finish with "
          "combat_special_assign. free_burst=true: reconciliation burst from NEGATIVE affinity with `partner` "
          "(-1: free L1 by whoever has the higher idea total; -2: free L3), ignores the chain, resets affinity to 0.")
    def combat_special(
        attacker: Annotated[str, P("cid performing it (current actor)")],
        level: Annotated[int, P("1, 2 or 3 (0 = automatic for free_burst)")] = 0,
        ideas: Annotated[dict, P("{attacker_cid: idea, partner_cid?: idea}; ideas: bravery|truth|compassion|justice")] = {},
        effect: Annotated[Optional[str], P("Elemental effect id belonging to the idea(s) used, or none")] = None,
        target: Annotated[Optional[str], P("L1 target cid; for L2/L3 it can set the area centre")] = None,
        at: Annotated[Optional[list[int]], P("[x,y] centre of the L2/L3 area")] = None,
        label: Annotated[str, P("Narrative label")] = "",
        free_burst: Annotated[bool, P("Reconciliation burst (needs partner and negative affinity)")] = False,
        allocations: Annotated[Optional[dict], P("{cid: damage} split for L2/L3; must sum to the total")] = None,
        partner: Annotated[Optional[str], P("Partner cid (default: the Bearer, or the first living Blade)")] = None,
        effect_target: Annotated[Optional[str], P("Recipient for beneficial effects")] = None,
        effect_art: Annotated[Optional[int], P("Art index for invigorating_steam")] = None,
        modifier: Annotated[int, P("Extra dice for the attacker")] = 0,
        force: Annotated[bool, P("Override rule violations")] = False,
    ) -> dict:
        return cm.combat_special(engine, attacker, level, ideas, effect, target, at, label, free_burst,
                                 allocations, partner, effect_target, effect_art, modifier, force)

    @tool(description="Finish a pending special_split by dividing the special's total damage among chosen targets "
          "in its area (allies may be spared simply by not listing them).")
    def combat_special_assign(
        allocations: Annotated[dict, P("{cid: damage}; must sum to the special's total")],
        force: Annotated[bool, P("Override")] = False,
    ) -> dict:
        return cm.combat_special_assign(engine, allocations, force)

    @tool(description="A non-attack action in combat (uses the action). kind 'other': roll `attribute` vs `check` "
          "(offensive=true if it directly engages an enemy, which forbids double movement); 'help_up': an adjacent "
          "ally uses its action to remove toppled (no roll); 'defend': take a guarding stance (no roll needed); "
          "'heal': Healer talent, unopposed art roll (needs art index) heals successes to target (cid or list), "
          "puts the art on cooldown and resets another art's cooldown (reset_art or the engine's pick).")
    def combat_action(
        cid: Annotated[str, P("Actor (current)")],
        label: Annotated[str, P("What they do")],
        attribute: Annotated[Optional[str], P("Attribute rolled (optional for no-roll actions): " + ATTR)] = None,
        check: Annotated[int, P("Difficulty (successes needed)")] = 0,
        modifier: Annotated[int, P("Extra dice/penalty")] = 0,
        kind: Annotated[str, P("other | help_up | defend | heal")] = "other",
        target: Annotated[Optional[Union[str, list[str]]], P("Target cid (or list for heal)")] = None,
        offensive: Annotated[bool, P("Directly engages an enemy")] = False,
        art: Annotated[Optional[int], P("Art index for heal")] = None,
        reset_art: Annotated[Optional[int], P("Art whose cooldown resets as the Healer cost")] = None,
        force: Annotated[bool, P("Override")] = False,
    ) -> dict:
        return cm.combat_action(engine, cid, label, attribute, check, modifier, kind, target, offensive, art,
                                reset_art, force)

    @tool(description="End the current actor's turn: sets facing, ticks cooldown dice (-1; frozen by arts_seal), "
          "ticks statuses, moves the actor to the bottom of the order, applies queued turn-order shifts "
          "(stagger/launch/electrifying burst), then starts the next actor's turn (burning damage, toppled => "
          "must_skip) and returns that actor's turn context. Blades may choose where to stand with blade_pos "
          "(a free square in the same radius).")
    def combat_end_turn(
        cid: Annotated[Optional[str], P("Must be the current actor (default: current)")] = None,
        facing: Annotated[Optional[str], P("N/E/S/W - end-of-turn facing")] = None,
        blade_pos: Annotated[Optional[list[int]], P("Blade only: final [x,y] within its current radius")] = None,
        force: Annotated[bool, P("Override")] = False,
    ) -> dict:
        return cm.combat_end_turn(engine, cid, facing, blade_pos, force)

    @tool(description="Turn swap: before acting, the current actor lets their teammate act now and takes the "
          "teammate's next slot. Locked until every team member has taken a turn.")
    def combat_swap_turn(
        cid: Annotated[str, P("Current actor")],
        partner: Annotated[Optional[str], P("Teammate cid (default: first living teammate)")] = None,
        force: Annotated[bool, P("Override")] = False,
    ) -> dict:
        return cm.combat_swap_turn(engine, cid, partner, force)

    @tool(description="Move a combatant later in the turn order by `places` immediately (talent Tactical Delay / GM "
          "fiat). Delaying the current actor passes the turn to the next one.")
    def combat_delay(
        cid: Annotated[str, P("Who is delayed")],
        places: Annotated[int, P("How many places later")],
        force: Annotated[bool, P("Override")] = False,
    ) -> dict:
        return cm.combat_delay(engine, cid, places, force)

    @tool(description="Resolve `pending: life_force`: a Bearer would drop to 0 HP or less and a Blade may pay its own "
          "HP to restore them. The Bearer is restored to `give` HP (>= 1); the Blade pays the damage needed to bring "
          "the Bearer from its would-be HP to `give`, plus 1 (Protective Aegis: no +1; Final Flicker: Bearer to 1 "
          "for all of the Blade's HP, final_flicker=true). decline=true: Bearer and natural Blades are downed. "
          "Remember the player must agree for their PC to go down.")
    def combat_life_force(
        blade: Annotated[Optional[str], P("Blade cid paying (optional if only one can)")] = None,
        give: Annotated[Optional[int], P("HP the Bearer is restored to")] = None,
        decline: Annotated[bool, P("Do not share: Bearer (and natural Blades) go down")] = False,
        final_flicker: Annotated[bool, P("Use Final Flicker")] = False,
        force: Annotated[bool, P("Override")] = False,
    ) -> dict:
        return cm.combat_life_force(engine, blade, give, decline, final_flicker, force)

    @tool(description="GM fiat batch - the escape hatch for talents, terrain and anything not automated. ops: "
          "damage{cid,n} heal{cid,n} set_hp{cid,n} max_hp{cid,n} status_add{cid,id,remaining,unit?(own_turns|"
          "until_source_turn_start|until_source_turn_end),source?,data?,kind?,label?} status_remove{cid,id} "
          "move{cid,to} face{cid,dir} shift_order{cid,delta (+ = sooner, - = later)} set_order{order} "
          "special_points{team_id,delta|value} cooldown{cid,art,value} add_combatant{like combat_start entry, "
          "index?} remove_combatant{cid} down{cid} revive{cid,hp} cell{x,y,type|null,label?...} "
          "chain_level{value} card{cid,patch} set_side{cid,side}.")
    def combat_adjust(
        ops: Annotated[list[dict], P("List of operations, each with an 'op' key")],
        reason: Annotated[str, P("Why (written to the combat log)")] = "",
    ) -> dict:
        return cm.combat_adjust(engine, ops, reason)

    @tool(description="End the combat: writes a journal event, copies HP back to the characters (full restore by "
          "default), resets per-combat talents, clears the grid.")
    def combat_end(
        outcome: Annotated[str, P("victory | defeat | fled | truce | other")],
        summary: Annotated[str, P("One or two sentences for the journal")] = "",
        restore_hp: Annotated[bool, P("Restore everyone to max HP (default) instead of keeping combat HP")] = True,
    ) -> dict:
        return cm.combat_end(engine, outcome, summary, restore_hp)
