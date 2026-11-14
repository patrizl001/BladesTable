"""Reference lookups: GM guide, rulebook sections, talent catalog. Tolerates missing data files."""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from typing import Any, Iterable, Optional

from . import rules
from .rules import DATA_DIR

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "is", "it", "for", "with", "as", "at",
         "by", "be", "do", "does", "how", "what", "can", "i", "my", "you", "your"}


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(str(text).lower()) if w not in _STOP]


def bm25_rank(query: str, docs: list[str], k1: float = 1.4, b: float = 0.75,
              title_boost: Optional[list[str]] = None) -> list[tuple[int, float]]:
    """Return [(doc_index, score)] for docs with score > 0, best first."""
    q = tokenize(query)
    if not q or not docs:
        return []
    toks = [tokenize(d) for d in docs]
    tt = [set(tokenize(t)) for t in title_boost] if title_boost else None
    n = len(docs)
    avg = sum(len(t) for t in toks) / n or 1.0
    df: dict[str, int] = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    out = []
    for i, t in enumerate(toks):
        tf: dict[str, int] = {}
        for w in t:
            tf[w] = tf.get(w, 0) + 1
        score = 0.0
        for w in set(q):
            f = tf.get(w, 0)
            if not f:
                # prefix match fallback (plural/stem)
                f = sum(c for x, c in tf.items() if len(w) > 3 and (x.startswith(w) or w.startswith(x)) and len(x) > 3) * 0.5
            if f:
                idf = math.log(1 + (n - df.get(w, 0) + 0.5) / (df.get(w, 0) + 0.5))
                score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * len(t) / avg))
            if tt and w in tt[i]:
                score += 2.0
        if score > 0:
            out.append((i, score))
    out.sort(key=lambda x: -x[1])
    return out


def _load_json(name: str) -> Optional[dict]:
    try:
        with open(DATA_DIR / name, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def not_built(what: str) -> dict:
    return {"ok": False, "errors": [f"data not built yet: {what} (boe/data is still being generated)"]}


# ------------------------------------------------------------------ guide
@lru_cache(maxsize=4)
def _guide_cached(path: str, mtime: float) -> dict:
    text = open(path, encoding="utf-8").read()
    pre, sections = "", []
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = {"raw_title": line[3:].strip(), "lines": []}
            sections.append(cur)
        elif cur is None:
            pre += line + "\n"
        else:
            cur["lines"].append(line)
    out = []
    for s in sections:
        t = s["raw_title"]
        core = t.lower().startswith("[core]")
        title = re.sub(r"^\[core\]\s*", "", t, flags=re.I)
        out.append({"title": title, "core": core, "text": "\n".join(s["lines"]).strip()})
    return {"preamble": pre.strip(), "sections": out}


def guide() -> Optional[dict]:
    p = DATA_DIR / "gm_guide.md"
    try:
        return _guide_cached(str(p), p.stat().st_mtime)
    except OSError:
        return None


def core_guide_text() -> str:
    g = guide()
    if not g:
        return ""
    parts = [g["preamble"]] if g["preamble"] else []
    parts += [f"## {s['title']}\n{s['text']}" for s in g["sections"] if s["core"]]
    return "\n\n".join(parts)


def gm_guide(topic: str = "") -> dict:
    g = guide()
    if not g:
        return not_built("gm_guide.md")
    titles = [s["title"] for s in g["sections"]]
    if not topic.strip():
        return {"ok": True, "sections": titles,
                "hint": "call gm_guide(topic=<title or part of a title>) to read one section"}
    t = topic.strip().lower()
    t = re.sub(r"^\[core\]\s*", "", t)
    hits = [s for s in g["sections"] if t == s["title"].lower()] or \
           [s for s in g["sections"] if t in s["title"].lower()]
    if not hits:
        return {"ok": False, "errors": [f"no GM guide section matches {topic!r}"], "sections": titles}
    return {"ok": True, "sections": [{"title": s["title"], "text": s["text"]} for s in hits]}


# ------------------------------------------------------------------ rules
def rules_lookup(query: str, limit: int = 3) -> dict:
    data = _load_json("rules_sections.json")
    if data is None:
        return not_built("rules_sections.json")
    secs = data.get("sections", [])
    docs = [f"{s.get('title','')} {s.get('title','')} {s.get('text','')}" for s in secs]
    ranked = bm25_rank(query, docs, title_boost=[s.get("title", "") for s in secs])
    limit = max(1, min(int(limit), 8))
    res = []
    for i, sc in ranked[:limit]:
        s = secs[i]
        txt = s.get("text", "")
        if len(txt) > 2500:
            txt = txt[:2500].rsplit(" ", 1)[0] + " ..."
        res.append({"title": s.get("title"), "chapter": s.get("chapter"), "page": s.get("page"),
                    "text": txt, "score": round(sc, 2)})
    if not res:
        return {"ok": True, "results": [], "note": "no rulebook section matched; try other keywords"}
    return {"ok": True, "results": res}


# ---------------------------------------------------------------- talents
def talent_lookup(query: str = "", category: str = "", role: str = "") -> dict:
    cat = rules.talent_catalog()
    if cat is None:
        return not_built("talents.json")
    items = cat
    if category:
        items = [t for t in items if t.get("category") == category]
    if role:
        items = [t for t in items if t.get("role") in (role, "any")]
    if query.strip():
        docs = [f"{t.get('name','')} {t.get('name','')} {t.get('text','')}" for t in items]
        rk = bm25_rank(query, docs, title_boost=[t.get("name", "") for t in items])
        s = rules.slug(query)
        exact = [t for t in items if rules.slug(t.get("name", "")) == s or t.get("id") == s]
        items = exact + [items[i] for i, _ in rk if items[i] not in exact]
        items = items[:12]
        return {"ok": True, "count": len(items), "talents": [_talent_row(t) for t in items]}
    # browsing (no query): compact one-line rows; query a name for the full text
    rows = []
    for t in items:
        r = _talent_row(t)
        bits = [f"rank {r['rank']}", str(r.get("role") or "any")]
        if r.get("requires"):
            bits.append("needs " + json.dumps(r["requires"], separators=(",", ":")))
        if r.get("creation_only"):
            bits.append("creation-only")
        if r.get("per"):
            bits.append(f"per {r['per']}")
        txt = r["text"].replace("\n", " ")
        rows.append(f"{r['name']} ({'; '.join(bits)}): {txt[:90]}{'...' if len(txt) > 90 else ''}")
    return {"ok": True, "count": len(rows), "talents": rows,
            "hint": "compact browse view; talent_lookup(query='<name>') returns the full rules text and requirements"}


def _talent_row(t: dict) -> dict:
    lo, hi = rules.talent_rank_range(t)
    row = {"id": t.get("id"), "name": t.get("name"), "rank": lo if lo == hi else f"{lo}-{hi}",
           "category": t.get("category"), "kind": t.get("kind"), "role": t.get("role")}
    req = {k: v for k, v in (t.get("requires") or {}).items() if v}
    if req:
        row["requires"] = req
    for k in ("creation_only", "per", "excludes"):
        if t.get(k):
            row[k] = t[k]
    row["text"] = t.get("text", "")
    return row


def bestiary(bid: str) -> Optional[dict]:
    d = _load_json("bestiary.json")
    if not d:
        return None
    s = rules.slug(bid)
    for e in d.get("enemies", []):
        if e.get("id") == bid or rules.slug(e.get("id", "")) == s or rules.slug(e.get("name", "")) == s:
            return e
    return None
