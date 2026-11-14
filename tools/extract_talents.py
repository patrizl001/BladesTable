"""Extract chapter 6 (talents) into boe/data/talents.json.

Reads PDF pages 45-64 (printed pp. 40-59) as reading-order blocks. Structural metadata
(category/role/kind) comes from the book's section headings; hand-curated overrides
(ids the code relies on, 'per' markers, kind of archetype sub-talents) are listed below.
"""
import re

from pdfblocks import page_blocks, reflow

PDF_FIRST, PDF_LAST = 45, 64
PRINTED_OFFSET = 5            # printed page = pdf page - 5
STORY_PAGES = {59, 62}        # pages that are pure fiction (example of play for archetypes)
RESET_PAGES = {59, 60, 62, 63}  # a talent never continues across these page starts

ATTRS = ["might", "willpower", "calculation", "gut", "experience", "knowledge", "stamina",
         "empathy", "attunement", "swiftness", "improvisation", "passion"]

HEADINGS = {
    "Chapter 6: List of Talents", "Universal Talents", "Bearer Talents", "Blade Talents",
    "Pair Talents", "Archetype Talents", "Bearer Archetype Talents", "Blade Archetype Talents",
    "Pair Archetype Talents", "General", "Combat", "Untouched Talents", "Telethial Talents",
    "Artificial Core Talents", "Flesh Eater Talents", "Body, Core, and Soul Talents",
}

ID_OVERRIDE = {"Body, Core, and Soul": "body_core_soul"}

# Archetype sub-talents: the book does not split them into General/Combat; judged by content.
SUB_COMBAT = {
    "Etheric Reflector", "Negative Presence", "Drakos' Wings", "Soul Read", "Disciple's Control",
    "Endbringer's Power", "Ether Furnace Overdrive", "Lease on Life", "Bond Forged in Battle",
    "Sword Cross", "Resynchronize", "Explosive Emotion",
}

# 'per' (usage limit), verified against the text of each talent.
PER = {
    "Interpersonal Deduction": "arc", "The Next Thing You're Going to Say Is...": "arc",
    "I Love You...and All You Guys!": "arc", "Just a Flesh Wound": "once",
    "Power Dive": "combat", "Switch Art": "combat", "The Last Laugh": "combat",
    "Point Blank": "combat", "Eagle Eye": "combat", "Exit Strategy": "arc", "Vanguard": "combat",
    "THINK YOU CAN TAKE ME?": "combat", "Titan Driver": "arc", "To Me!": "combat",
    "Trebu-Blade": "combat", "Essence Exchange": "combat", "To You!": "combat",
    "Distracting Strike": "combat", "Ghost Factory": "combat", "Orbital Death Beam": "arc",
    "Premonitions": "combat", "Forgotten Flash": "arc", "Drakos' Wings": "combat",
    "Soul Read": "combat", "Bond Forged in Battle": "combat", "Carry On": "arc",
    "Body, Core, and Soul": "combat",
}
REPEATABLE = {"Old Friends"}

ARCH_ROLE = {"Untouched": "bearer", "Telethial": "bearer", "Artificial Core": "blade",
             "Flesh Eater": "blade", "Dying Devotion": "pair", "Body, Core, and Soul": "pair"}

ARCHETYPE_IDS = {
    "Untouched Talents": "untouched", "Telethial Talents": "telethial",
    "Artificial Core Talents": "artificial_core", "Flesh Eater Talents": "flesh_eater",
    "Body, Core, and Soul Talents": "body_core_soul",
}

HDR = re.compile(r"^(.*?)\s*\(Rank (\d+)(?:-(\d+))?\)$")


def make_id(name):
    if name in ID_OVERRIDE:
        return ID_OVERRIDE[name]
    s = name.lower().replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def parse_header(lines):
    """Return (name, rank_lo, rank_hi, consumed_lines) or None."""
    m = HDR.match(lines[0])
    if m and m.group(1):
        return m.group(1).strip(), int(m.group(2)), m.group(3) and int(m.group(3)), 1
    if len(lines) > 1:
        m2 = HDR.match(lines[1])
        if m2 and "(Rank" not in lines[0]:
            name = (lines[0] + " " + m2.group(1)).strip()
            return name, int(m2.group(2)), m2.group(3) and int(m2.group(3)), 2
    return None


def parse_requirement(line, name_to_id):
    req = {"attributes": {}, "talents": [], "archetype": None}
    body = re.sub(r"^Requires\s+", "", line.strip())
    for part in re.split(r"\s+and\s+", body):
        m = re.match(r"^(\d+)\s+([a-z]+)$", part)
        if m and m.group(2) in ATTRS:
            req["attributes"][m.group(2)] = int(m.group(1))
        else:
            req["talents"].append(part)    # resolved to ids after all names are known
    return req


def extract(pdf, used=None):
    """Parse talents. If `used` (a set) is given, (pdf_page, block_index) of every block that
    belongs to a talent is added to it, so other extractors can skip them."""
    talents = []
    order_names = []
    cur = None                 # talent being built (dict with 'blocks')
    cat, role, kind, arch = None, None, "general", None
    last_block_lines = None
    for pg in range(PDF_FIRST, PDF_LAST + 1):
        if pg in RESET_PAGES:
            cur = None
        if pg in STORY_PAGES:
            continue
        for bi, b in enumerate(page_blocks(pdf, pg)):
            lines = [l.strip() for l in b["lines"] if l.strip()]
            if not lines or re.fullmatch(r"\d+", lines[0]):
                continue
            if len(lines) == 1 and lines[0] in HEADINGS:
                h = lines[0]
                cur = None
                if h == "Universal Talents":
                    cat, role, kind, arch = "universal", "any", "general", None
                elif h == "Bearer Talents":
                    cat, role, kind, arch = "bearer", "bearer", "general", None
                elif h == "Blade Talents":
                    cat, role, kind, arch = "blade", "blade", "general", None
                elif h == "Pair Talents":
                    cat, role, kind, arch = "pair", "pair", "general", None
                elif h == "Archetype Talents":
                    cat, role, kind, arch = "archetype", "any", "general", None
                elif h == "Bearer Archetype Talents":
                    cat, role, kind, arch = "archetype", "bearer", "general", None
                elif h == "Blade Archetype Talents":
                    cat, role, kind, arch = "archetype", "blade", "general", None
                elif h == "Pair Archetype Talents":
                    cat, role, kind, arch = "archetype", "pair", "general", None
                elif h in ARCHETYPE_IDS:
                    cat, kind, arch = "archetype_talent", "general", ARCHETYPE_IDS[h]
                    if arch == "body_core_soul":
                        role = "pair"
                elif h in ("General", "Combat"):
                    kind = h.lower()
                continue
            hd = parse_header(lines)
            if hd:
                name, lo, hi, nlines = hd
                name = reflow([name])            # normalise typographic quotes
                if name in ARCH_ROLE:            # an archetype itself (not under a sub-heading)
                    cat, role, kind, arch = "archetype", ARCH_ROLE[name], "general", None
                rest = lines[nlines:]
                t = {"name": name, "lo": lo, "hi": hi, "cat": cat, "role": role, "kind": kind,
                     "arch": arch, "req_line": None, "excl_line": None, "creation": False,
                     "body": [], "page": pg - PRINTED_OFFSET}
                while rest and (rest[0].startswith("Requires ") or rest[0].startswith("Cannot be taken with ")
                                or rest[0] == "Character creation only"):
                    l = rest.pop(0)
                    if l.startswith("Requires "):
                        t["req_line"] = l
                    elif l.startswith("Cannot be taken"):
                        t["excl_line"] = l
                    else:
                        t["creation"] = True
                t["body"].append(rest)
                talents.append(t)
                cur = t
                if used is not None:
                    used.add((pg, bi))
                continue
            if cur is None:
                continue                     # intro prose / story text
            # continuation block of the current talent (flavour paragraph, mascot option, list)
            if used is not None:
                used.add((pg, bi))
            if all(l == "•" for l in lines):
                continue
            prev = cur["body"][-1] if cur["body"] else []
            if prev and prev[-1].endswith(":") and all(len(l) < 30 for l in lines):
                cur["body"].append([", ".join(lines) + "."])
            else:
                cur["body"].append(lines)
    # ---- build records
    name_to_id = {t["name"]: make_id(t["name"]) for t in talents}
    out = []
    for t in talents:
        name = reflow([t["name"]])
        text = " ".join(reflow(b) for b in t["body"] if b)
        text = re.sub(r"\s+", " ", text).strip()
        req = {"attributes": {}, "talents": [], "archetype": t["arch"] if t["cat"] == "archetype_talent" else None}
        if t["req_line"]:
            r = parse_requirement(reflow([t["req_line"]]), name_to_id)
            req["attributes"] = r["attributes"]
            req["talents"] = [make_id(reflow([x])) if reflow([x]) not in ID_OVERRIDE else ID_OVERRIDE[x]
                              for x in r["talents"]]
        excludes = []
        if t["excl_line"]:
            nm = reflow([t["excl_line"]]).replace("Cannot be taken with ", "")
            excludes = [make_id(nm)]
        tid = make_id(name)
        rank = t["lo"] if t["hi"] is None else None
        out.append({
            "id": tid, "name": name, "rank": rank,
            "rank_min": None if t["hi"] is None else t["lo"],
            "rank_max": t["hi"],
            "category": t["cat"], "kind": ("combat" if (t["cat"] == "archetype_talent" and t["name"] in SUB_COMBAT)
                                           else t["kind"] if t["cat"] != "archetype_talent" else "general"),
            "role": t["role"],
            "requires": req, "creation_only": t["creation"], "excludes": excludes,
            "per": PER.get(t["name"]), "repeatable": t["name"] in REPEATABLE,
            "text": text, "page": t["page"],
        })
    return out
