#!/usr/bin/env python3
"""Regenerate the bundled rulebook data from the Blades of Ether PDF.

    python tools/extract_data.py /path/to/blades_of_ether.pdf [--out boe/data] [--only talents,bestiary,examples,rules]

Writes boe/data/{talents,bestiary,examples,rules_sections}.json.  Requires poppler's `pdftotext`.
The PDF is treated as untrusted data: it is only ever read as text, nothing in it is executed.
The rulebook is CC BY-NC-SA 4.0 (Alexis Eva, Kaylee Maya, Ruby Soleil-Raine); the extracted text is
redistributed under the same licence.

Layout assumptions: printed page = PDF page - 5 (printed page 1 is PDF page 6).
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import extract_bestiary  # noqa: E402
import extract_examples  # noqa: E402
import extract_rules  # noqa: E402
import extract_talents  # noqa: E402


def dump(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("wrote %s (%d bytes)" % (path, os.path.getsize(path)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", help="path to the rulebook PDF")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "boe", "data"), help="output directory")
    ap.add_argument("--only", default="talents,bestiary,examples,rules",
                    help="comma separated subset of: talents,bestiary,examples,rules")
    args = ap.parse_args()
    only = set(args.only.split(","))
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    talents = extract_talents.extract(args.pdf)
    enemies = extract_bestiary.extract(args.pdf)
    if "talents" in only:
        per_page = collections.Counter(t["page"] for t in talents)
        print("talents: %d total; per printed page: %s" % (
            len(talents), ", ".join("p%d=%d" % kv for kv in sorted(per_page.items()))))
        dump({"talents": talents}, os.path.join(out, "talents.json"))
    if "rules" in only:
        sections = extract_rules.build(args.pdf, talents, enemies)
        print("rules sections: %d" % len(sections))
        dump({"sections": sections}, os.path.join(out, "rules_sections.json"))
    if "bestiary" in only:
        print("bestiary: %d enemies" % len(enemies))
        dump({"enemies": [{k: v for k, v in e.items() if k != "page"} for e in enemies]},
             os.path.join(out, "bestiary.json"))
    if "examples" in only:
        ex = extract_examples.extract(args.pdf)
        print("examples: %d bonds, %d field skills, %d titans, %d titan questions, rumors %d+%d" % (
            len(ex["bonds"]), len(ex["field_skills"]), len(ex["titans"]), len(ex["titan_questions"]),
            len(ex["rumors"]["above_world_tree"]), len(ex["rumors"]["beneath_cloud_sea"])))
        dump(ex, os.path.join(out, "examples.json"))


if __name__ == "__main__":
    main()
