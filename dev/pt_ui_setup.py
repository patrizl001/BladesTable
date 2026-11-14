"""Leave the running campaign mid-combat with interesting UI content (statuses, specials, rolls). Dev only."""
import asyncio, json, os, random, sys
sys.path.insert(0, os.path.dirname(__file__))
from mcpc import connect
from playtest_common import Table
import pt_combat as pc

async def main(step):
    async with connect() as (s, init):
        t = Table(s); ct = pc.CT(t, random.Random(3), verbose=False)
        if step == "start":
            await ct("combat_start", name="Yard fight", map={"width": 10, "height": 8, "name": "Rustwharf yard", "cells": pc.CELLS},
                     combatants=[{"char_id": pc.HERO, "pos": [1, 3], "facing": "E"}, {"char_id": pc.BLADE, "pos": [1, 4]},
                                 {"name": "Pack Animal", "bestiary": "pack_animal", "pos": [6, 3]}, {"name": "Pack Animal", "bestiary": "pack_animal", "pos": [6, 4]},
                                 {"name": "Cinder Captain", "card": pc.CARD, "pos": [8, 5]}, {"name": "Cinder Edge", "card": dict(pc.CARD, role="blade", hp=6), "bearer": "Cinder Captain", "pos": [7, 5]}],
                     feeling_it=[{"char_id": pc.HERO, "attribute": "swiftness", "reason": "proving himself"}])
            await ct.sync()
            for _ in range(6):
                await ct.auto_turn()
            await ct("combat_adjust", ops=[{"op": "status_add", "cid": "pack_animal_1", "id": "burning", "remaining": 3},
                                           {"op": "status_add", "cid": pc.HERO, "id": "blustering_gale", "remaining": 2},
                                           {"op": "special_points", "team_id": "t_kael-varrow", "value": 14}])
        print(json.dumps((await ct.sync()) and {"order": ct.c["order"]}))
asyncio.run(main(sys.argv[1]))
