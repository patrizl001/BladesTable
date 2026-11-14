"""Build a clean paragraph stream of the whole rulebook (printed page numbers)."""
import re

from pdfblocks import all_pages, clean, reflow
import extract_talents

OFF = 5
TERMINAL = re.compile(r"[.!?\"'…):]$")

# ---- clean hand-written versions of tables that do not survive text extraction -------------
T_ART_TAGS = """Art tags (base category cost in bond points)
Category | Category cost | Tags
Fundamentals | 3 | Potency +1 (max 5); Healing Potion; Cooldown -1 (max 2)
Area of Effect | 15 | Circle Attack (max 2); Line Attack
Reactions | 5 | Break; Topple; Launch; Stagger; Rush (max 2)
Positionals | 3 | Side Advantage (Bearers only); Rear Advantage (Bearers only); Pincer Attack (Blades only)
Elemental Effects | 4, requires affinity | Unique Elemental Effect (any element); Invigorating Steam (fire or water); Bitter Snowstorm (wind or ice); Counter Spike (earth or electricity); Blinding Eclipse (light or dark)
Other | cost varies | Range +1 (base cost 2, max 5); Precise Attack (cost 10)"""

T_CREATION_TAGS = """Art tags at character creation (cost in tags)
Category | Creation cost | Tags
Fundamentals | 1 | Potency +1 (max 5); Healing Potion; Cooldown -1 (max 2)
Area of Effect | 3 | Circle Attack (max 2); Line Attack
Reactions | 1 | Break; Topple; Launch; Stagger; Rush (max 2)
Positionals | 1 | Side Advantage (Bearers only); Rear Advantage (Bearers only); Pincer Attack (Blades only)
Elemental Effects | 1, requires affinity | Unique Elemental Effect (any element); Invigorating Steam (fire or water); Bitter Snowstorm (wind or ice); Counter Spike (earth or electricity); Blinding Eclipse (light or dark)
Other | cost varies | Range +1 (cost 1, max 5); Precise Attack (cost 2)
Example art from the book: Art 1, "Anchor Toss" - Description: pulls the enemy down with a hook on a rope. Tags: Healing Potion, Topple; Potency +1; Cooldown -0; Range +2."""

T_START_NOTES = ("Character Creation Starting Points. Attributes: 1 point allows you to increase an attribute by 1. "
                 "Ranks above 4 cost 2 points. Ranks above 8 cost 3 points. Field skills: field skills do not come in "
                 "tiered rankings, so create the suggested number of skills. Arts: start with a free Potency +1 tag. "
                 "You have a number of tags per art to claim, but can only spend so much in any one category. Taking a "
                 "tag from the area of effect category counts as 3 tags, and taking the Precise Attack tag counts as 2. "
                 "Talents: acquire talents whose total rank equals the number listed.")
T_START = T_START_NOTES + """
Starting point | Attribute points | Field skills | Arts (tags per art) | Talents (total rank)
Fresh face | 8 points | 2 field skills | 2 tags, max 1 per category | 5 ranks
Part-time hero | 16 points | 3 field skills | 4 tags, max 2 per category | 8 ranks
Veteran | 24 points | 4 field skills | 6 tags, max 2 per category | 11 ranks
Titan savior | 32 points | 5 field skills | 8 tags, max 3 per category | 14 ranks"""

T_UPGRADE = """Upgrade Bond Points Costs
Upgrade | Bond Points
Attribute | 2 x new rank
Elemental affinity | 7 x new total number of affinities
Field skill | 3 per field skill
Talent | 3 x talent rank
Basic attack range | 2 x new total bonus range (maximum 5)
Categorized arts tag | Cat. cost x new number of tags in that category on that art
Other arts tag | Precise Attack: 10; Range +1: 2 x new total bonus range"""

T_DICEPOOL = """Player Attributes and Dice Pool Results (for balancing enemy values)
Attribute strength | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12
Average successes | 0.33 | 0.67 | 1.00 | 1.33 | 1.67 | 2.00 | 2.33 | 2.67 | 3.00 | 3.33 | 3.67 | 4.00
Check often lost | 1 | 1 | 2 | 2 | 2 | 3 | 3 | 3 | 4 | 4 | 4 | 5
Check often met | 0 | 0 | 1 | 1 | 1 | 2 | 2 | 2 | 3 | 3 | 3 | 4
Check often beaten | 0 | 0 | 0 | 1 | 1 | 1 | 2 | 2 | 2 | 3 | 3 | 3"""

T_NPC_CARD = ("Enemy card layout: Name; Role; M (movement) and I (initiative) "
              "boxes; Attacks; Defenses; HP; Affinities; Attributes (best attributes); Notes; Art tags; Special abilities.")

ERRATUM_IDEAS = ("[Erratum: this list swaps truth and compassion. Everywhere else in the book (p.9, the art-tag table, the "
                 "glossary) truth = wind or ice and compassion = earth or electricity.]")

T_AFFINITY_LIST = ("Bravery: fire or water. Truth: earth or electricity. Compassion: wind or ice. Justice: light or dark. "
                   + ERRATUM_IDEAS)

# region config: pdf page -> list of (xmin, xmax, ymin, ymax, text|None)  (blocks starting there are dropped; the text,
# if any, is emitted as an injected paragraph at the position of the first dropped block)
REGIONS = {
    28: [(0, 700, 242, 470, T_ART_TAGS)],
    39: [(0, 700, 150, 200, "Attribute points at creation: Fresh face: allot 8 points. Part-time hero: allot 16 points. "
                           "Veteran: allot 24 points. Titan savior: allot 32 points."),
         (0, 700, 505, 550, T_AFFINITY_LIST)],
    40: [(0, 700, 195, 240, "Field skills at creation: Fresh face: write 2 field skills. Part-time hero: write 3 field "
                            "skills. Veteran: write 4 field skills. Titan savior: write 5 field skills.")],
    41: [(398, 700, 0, 290, None), (0, 700, 320, 545, T_CREATION_TAGS)],
    42: [(0, 700, 0, 130, "Talents at creation: Fresh face: acquire talents with total rank 5. Part-time hero: acquire "
                          "talents with total rank 8. Veteran: acquire talents with total rank 11. Titan savior: acquire "
                          "talents with total rank 14."),
         (0, 700, 520, 760, T_START)],
    43: [(0, 700, 520, 760, T_UPGRADE)],
    79: [(0, 700, 85, 215, T_NPC_CARD), (0, 700, 535, 655, T_DICEPOOL)],
    83: [(0, 700, 290, 760, None)],
}
SKIP_PAGES = {1, 2, 4 - 0, 5, 84, 85, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 86 - 0}
DROP_LINES = {"An example battle grid.", "The three radii around a Bearer.", "Range", "+ 2", "An example art."}
DROP_BLOCK_TEXT = {"\u2191", "\u2193"}
DROP_TEXT = {"Untouched Talents", "Telethial Talents", "Artificial Core Talents", "Flesh Eater Talents",
             "Body, Core, and Soul Talents"}      # sub-headings of the talent chapter (not tall enough to be 'h')


def build(pdf):
    """Return list of items {page, kind, text}. kind: 'h' heading, 'p' paragraph, 'x' injected table text."""
    pages = all_pages(pdf)
    used = set()
    extract_talents.extract(pdf, used)
    out = []
    for pg in range(3, 97):
        if pg in (86,):
            blocks = [b for b in pages[pg] if b["y"] < 225]
        elif pg in SKIP_PAGES and pg != 4:
            continue
        else:
            blocks = pages[pg]
        printed = max(pg - OFF, 0)
        emitted = set()
        for bi, b in enumerate(blocks):
            if (pg, bi) in used and 45 <= pg <= 64:
                continue
            lines = [l for l in b["lines"] if l.strip() and l.strip() not in DROP_LINES]
            if not lines:
                continue
            t0 = lines[0].strip()
            if t0 in DROP_BLOCK_TEXT:
                continue
            if re.fullmatch(r"\d+", t0) and b["y"] > 735:
                continue                                    # page number
            if re.match(r"^Blades of Ether by Alexis", t0):
                continue
            region = None
            for ri, (x0, x1, y0, y1, txt) in enumerate(REGIONS.get(pg, [])):
                if x0 <= b["x"] <= x1 and y0 <= b["y"] <= y1:
                    region = (ri, txt)
                    break
            if region is not None:
                ri, txt = region
                if txt and ri not in emitted:
                    out.append({"page": printed, "kind": "x", "text": txt})
                    emitted.add(ri)
                continue
            text = reflow(lines)
            if text in DROP_TEXT:
                continue
            heading = (len(lines) == 1 and max(b["heights"]) >= 14)
            kind = "h" if heading else "p"
            if (out and kind == "p" and out[-1]["kind"] == "p" and out[-1]["page"] != printed
                    and not TERMINAL.search(out[-1]["text"])):
                out[-1]["text"] = reflow([out[-1]["text"], text])
                continue
            # same-page continuation across columns (rare): previous para unfinished and this starts lowercase
            if (out and kind == "p" and out[-1]["kind"] == "p" and not TERMINAL.search(out[-1]["text"])
                    and text[:1].islower() and out[-1]["page"] == printed and b["x"] > 300):
                out[-1]["text"] = reflow([out[-1]["text"], text])
                continue
            out.append({"page": printed, "kind": kind, "text": text})
    return out
