"""Helpers: read PDF pages as reading-order blocks of lines, keeping hyphens at line ends.

Uses `pdftotext -bbox-layout` (poppler), which does not de-hyphenate. Only data is read from
the PDF; nothing in it is ever executed.
"""
import html
import re
import subprocess

_CACHE = {}


def all_pages(pdf):
    """Return {pdf_page_number: [block, ...]} for the whole document (cached)."""
    if pdf in _CACHE:
        return _CACHE[pdf]
    out = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"],
                         check=True, capture_output=True, text=True).stdout
    pages = {}
    for n, pg in enumerate(re.findall(r"<page .*?</page>", out, flags=re.S), start=1):
        blocks = []
        for blk in re.findall(r"<block .*?</block>", pg, flags=re.S):
            m = re.search(r'<block xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"', blk)
            lines, heights, xs, ys, words_l = [], [], [], [], []
            for ln in re.findall(r"<line .*?</line>", blk, flags=re.S):
                words = [html.unescape(w) for w in re.findall(r">([^<]*)</word>", ln)]
                wx = [float(v) for v in re.findall(r'<word xMin="([\d.]+)"', ln)]
                words_l.append(list(zip(wx, words)))
                lines.append(" ".join(words))
                lm = re.search(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"', ln)
                heights.append(round(float(lm.group(4)) - float(lm.group(2)), 1))
                xs.append(float(lm.group(1)))
                ys.append(float(lm.group(2)))
            if lines:
                blocks.append({"x": float(m.group(1)), "y": float(m.group(2)),
                               "xmax": float(m.group(3)), "ymax": float(m.group(4)),
                               "lines": lines, "heights": heights, "xs": xs, "ys": ys, "words": words_l})
        pages[n] = blocks
    _CACHE[pdf] = pages
    return pages


def page_blocks(pdf, page):
    return all_pages(pdf)[page]


FIXES = [("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), (" ", " ")]


def clean(text):
    for a, b in FIXES:
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def reflow(lines):
    """Join wrapped lines into prose. A trailing '-' is a real hyphen (kept, no space)."""
    text = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not text:
            text = ln
        elif text.endswith("-") and ln[:1].islower():
            text += ln
        else:
            text += " " + ln
    return clean(text)
