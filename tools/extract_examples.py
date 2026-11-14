"""Extract example bonds, field skills, Titans, Titan-creation questions and world-tree rumors."""
import re

from pdfblocks import all_pages, clean, reflow

OFF = 5


def _paras(pdf, first, last, skip=None):
    """Paragraph list [(printed_page, kind, text)] for PDF pages first..last.
    Blocks that continue the previous one across a page are merged."""
    pages = all_pages(pdf)
    out = []
    for pg in range(first, last + 1):
        for b in pages[pg]:
            lines = [l for l in b["lines"] if l.strip()]
            if not lines or re.fullmatch(r"\d+", lines[0].strip()):
                continue
            text = reflow(lines)
            kind = "h" if (len(lines) == 1 and max(b["heights"]) >= 14 and abs((b["x"] + b["xmax"]) / 2 - 306) < 40) else "p"
            if skip and skip(text, kind):
                continue
            if out and kind == "p" and out[-1][1] == "p" and out[-1][0] != pg - OFF and \
                    not re.search(r"[.!?\"'…)]$", out[-1][2]) and text[:1].islower():
                out[-1] = (out[-1][0], "p", reflow([out[-1][2], text]))
                continue
            out.append((pg - OFF, kind, text))
    return out


def labelled(paras, label_re=r"^([^:]{2,40}): (.*)$"):
    res = []
    for _, kind, text in paras:
        if kind != "p":
            continue
        m = re.match(label_re, text)
        if m:
            res.append({"name": m.group(1).strip(), "text": m.group(2).strip()})
    return res


def extract(pdf):
    # --- bonds (printed 11-12): paragraphs "Name: text" between "Example Bonds" and "Play Tips"
    paras = _paras(pdf, 16, 17)
    start = next(i for i, p in enumerate(paras) if p[2] == "Example Bonds")
    end = next(i for i, p in enumerate(paras) if p[2].startswith("Play Tips"))
    bonds = labelled(paras[start + 1:end])
    # --- field skills (printed 16)
    paras = _paras(pdf, 21, 21)
    skills = labelled(paras[1:])
    # --- titans (printed 60-63)
    paras = _paras(pdf, 65, 68)
    titans, cur = [], None
    names = ["Gentarum", "Morgot", "Raya", "Mordania", "Leftria", "Idnol", "Bengu", "Ronat", "The Waning Warriors"]
    for _, kind, text in paras:
        if kind == "h" and text in names:
            cur = {"name": text, "text": []}
            titans.append(cur)
        elif cur is not None and kind == "p":
            cur["text"].append(text)
    for t in titans:
        t["text"] = " ".join(t["text"])
    # --- titan-creation questions (printed 64-65)
    paras = _paras(pdf, 69, 70)
    qs = []
    for _, kind, text in paras:
        m = re.match(r"^((?:What|How|Who)[^?]*\?) (.*)$", text)
        if kind == "p" and m:
            qs.append({"name": m.group(1), "text": m.group(2)})
    # --- rumors (printed 65-66)
    paras = _paras(pdf, 70, 71)
    above, beneath, cur_list = [], [], None
    for _, kind, text in paras:
        if kind == "h" and text == "Above the World Tree":
            cur_list = above
        elif kind == "h" and text == "Beneath the Cloud Sea":
            cur_list = beneath
        elif kind == "p" and cur_list is not None:
            m = re.match(r"^([A-Z][A-Za-z' ]{2,30}): (.*)$", text)
            if m:
                cur_list.append({"name": m.group(1), "text": m.group(2)})
    return {"bonds": bonds, "field_skills": skills, "titans": titans, "titan_questions": qs,
            "rumors": {"above_world_tree": above, "beneath_cloud_sea": beneath}}
