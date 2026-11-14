"""Extract the example bestiary (chapter 9, printed pp.78-80 = PDF pages 83-85)."""
import re

from pdfblocks import all_pages, clean, reflow

PDF_PAGES = [83, 84, 85]
PRINTED_OFFSET = 5

TAG_IDS = {
    "break": "break", "topple": "topple", "launch": "launch", "stagger": "stagger", "rush": "rush",
    "unique elemental effect": "unique_effect", "unique elem. effect": "unique_effect",
}
ALL_REACTIONS = ["break", "topple", "launch", "stagger", "rush"]
ATTRS = ["might", "willpower", "calculation", "gut", "experience", "knowledge", "stamina",
         "empathy", "attunement", "swiftness", "improvisation", "passion"]
ELEMENTS = ["fire", "water", "wind", "ice", "earth", "electricity", "light", "dark"]


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def parse_tags(text):
    """Return (tag_ids, leftover_instruction_text)."""
    ids, left = [], []
    for part in [p.strip() for p in text.split(",") if p.strip()]:
        key = part.lower()
        if key in TAG_IDS:
            ids.append(TAG_IDS[key])
        elif key == "all reactions":
            ids.extend(ALL_REACTIONS)
        else:
            left.append(part)
    return ids, ", ".join(left)


def nums(text):
    return [int(x) for x in re.findall(r"\d+", text)]


def parse_card(items, split_items, y0, y_end):
    """items: list of (x, y, text) lines on the page. Parse the card between y0 and y_end."""
    card = [i for i in items if y0 - 4 <= i[1] < y_end]
    def row(y, tol=4):
        return sorted([i for i in card if abs(i[1] - y) <= tol], key=lambda i: i[0])

    r0 = row(y0)
    texts = [clean(i[2]) for i in r0]
    name = texts[texts.index("Name") + 1]
    role_m = next(re.match(r"Role (\w+)", t) for t in texts if t.startswith("Role "))
    role = role_m.group(1).lower()
    digits = [int(t) for t in texts if re.fullmatch(r"\d+", t)]
    movement, initiative = digits[0], digits[1]

    att = next(i for i in card if clean(i[2]) == "Attacks")
    r1 = [clean(i[2]) for i in row(att[1])]
    attack = nums(r1[r1.index("Attacks") + 1])
    defense = nums(r1[r1.index("Defenses") + 1])
    hp = nums(r1[r1.index("HP") + 1])[0]

    aff = next(i for i in card if clean(i[2]) == "Affinities")
    r2 = [clean(i[2]) for i in row(aff[1])]
    aff_text = r2[r2.index("Affinities") + 1]
    attr_text = next(t for t in r2 if t.startswith("Attributes")).replace("Attributes", "", 1).strip()

    rest = [i for i in split_items if y0 - 4 <= i[1] < y_end and i[1] > aff[1] + 6]
    left = sorted([i for i in rest if i[0] < 300], key=lambda i: i[1])
    right = sorted([i for i in rest if i[0] >= 300], key=lambda i: i[1])
    notes = reflow([i[2] for i in left if clean(i[2]) != "Notes"])
    sections, cur = {}, None
    for _, _, t in right:
        t = clean(t)
        if t in ("Art tags", "Special abilities"):
            cur = t
            sections[cur] = []
        elif cur:
            sections[cur].append(t)
    art_text = reflow(sections.get("Art tags", []))
    special_lines = sections.get("Special abilities", [])
    return {
        "name": name, "role": role, "attack": attack, "defense": defense, "hp": hp,
        "movement": movement, "initiative": initiative, "aff_text": aff_text,
        "attr_text": attr_text, "art_text": art_text, "special_lines": special_lines, "notes": notes,
    }


def parse_special(lines):
    entries, cur = [], None
    for ln in lines:
        m = re.match(r"^([A-Z][\w' ]*(?:: [A-Z][\w' ]*)?): (.*)$", ln) if not ln.startswith("Talent:") else None
        if ln.startswith("Talent: "):
            entries.append({"name": ln[len("Talent: "):].strip(), "text": "Has the talent %s." % ln[len("Talent: "):].strip()})
            cur = None
        elif m and (cur is None or entries[-1]["text"].rstrip().endswith((".", ")"))):
            entries.append({"name": m.group(1), "text": m.group(2)})
            cur = entries[-1]
        elif entries:
            entries[-1]["text"] = reflow([entries[-1]["text"], ln])
    for e in entries:
        e["text"] = clean(e["text"])
        if not e["text"].endswith((".", "!", "?")):
            e["text"] += "."
    return entries


def extract(pdf):
    pages = all_pages(pdf)
    enemies = []
    for pg in PDF_PAGES:
        items, split_items = [], []
        for b in pages[pg]:
            for words, y, t, x in zip(b["words"], b["ys"], b["lines"], b["xs"]):
                items.append((x, y, t))
                # a PDF text line can hold words of both columns: split at x=300
                for part in ([w for w in words if w[0] < 300], [w for w in words if w[0] >= 300]):
                    if part:
                        split_items.append((part[0][0], y, " ".join(w[1] for w in part)))
        starts = sorted(i[1] for i in items if clean(i[2]) == "Name")
        for n, y0 in enumerate(starts):
            y_end = starts[n + 1] - 4 if n + 1 < len(starts) else 745
            c = parse_card(items, split_items, y0, y_end)
            notes = [c["notes"]]
            affinities, best, tags = [], [], []
            at = c["aff_text"].strip()
            if at.lower() == "none":
                pass
            elif all(w.strip().lower() in ELEMENTS for w in at.split(",")):
                affinities = [w.strip().lower() for w in at.split(",")]
            else:
                notes.append("Affinities: " + at + ".")
            bt = c["attr_text"]
            if bt and all(w.strip().lower() in ATTRS for w in bt.split(",")):
                best = [w.strip().lower() for w in bt.split(",")]
            elif bt:
                notes.append("Best attributes: " + bt + ".")
            tags, left = parse_tags(c["art_text"])
            if left:
                notes.append("Art tags: " + left + ".")
            dis, norm, adv = c["attack"]
            ddis, dnorm, dadv = c["defense"]
            enemies.append({
                "id": slug(c["name"]), "name": c["name"], "role": c["role"],
                "attack": {"dis": dis, "normal": norm, "adv": adv},
                "defense": {"dis": ddis, "normal": dnorm, "adv": dadv},
                "hp": c["hp"], "movement": c["movement"], "initiative": c["initiative"],
                "affinities": affinities, "best_attributes": best, "art_tags": tags,
                "special_abilities": parse_special(c["special_lines"]),
                "notes": " ".join(n for n in notes if n),
                "page": pg - PRINTED_OFFSET,
            })
    return enemies
