"""Parse the Appendix of amendments and attach them to the articles they change."""
import json
import re
from collections import Counter
from pathlib import Path

from parse_law_en import clean_lines

RAW_TXT = Path("data/raw/labor_law_en.txt")
ARTICLES_JSON = Path("data/processed/labor_law_en.json")
AMENDMENTS_JSON = Path("data/processed/labor_law_en_amendments.json")

DATE = re.compile(r"^([A-Z][a-z]+ \d{1,2}, \d{4}) \((.+)\)$")
DECREE = re.compile(r"^Royal Decree No\. (M/\d+)")
INSTRUCTION = re.compile(r"^[^\w\"“]*(Amending|Repealing|Adding|Deleting|Renumbering|Replacing)\b")
ARTICLE_LIST = re.compile(r"Articles?\s+((?:\d+(?:\s*\(\d+\))?(?:\s*bis)?(?:\s*,?\s+and\s+|\s*,\s*)?)+)")
NUMBERED = re.compile(r"numbered\s+[\"“]?(?:Article\s+)?(\d+)")
BODY_HEADING = re.compile(r"^[\"“]?Article\s+(\d+)", re.MULTILINE)


def parse_appendix(lines: list[str]) -> list[dict]:
    lines = lines[lines.index("Appendix") + 1:]
    amendments, current = [], None
    date = hijri = decree = None

    for s in lines:
        if not re.search(r"\w", s):  # skip empty or bullet-only lines
            continue
        m_date, m_decree, m_instr = DATE.match(s), DECREE.match(s), INSTRUCTION.match(s)
        if m_date:
            date, hijri, current = m_date.group(1), m_date.group(2), None
        elif m_decree:
            decree, current = m_decree.group(1), None
        elif m_instr:
            current = {
                "id": f"labor_law-en-amd-{len(amendments) + 1}",
                "date": date,
                "hijri": hijri,
                "decree": decree,
                "action": m_instr.group(1),
                "instruction": s[m_instr.start(1):],
                "body_lines": [],
                "instruction_done": s.endswith((":", ".")),
            }
            amendments.append(current)
        elif current is not None:
            if current["instruction_done"]:
                current["body_lines"].append(s)
            else:  # the instruction sentence wrapped onto another line
                current["instruction"] += " " + s
                current["instruction_done"] = s.endswith((":", "."))

    for a in amendments:
        a["text"] = "\n".join(a.pop("body_lines"))
        a.pop("instruction_done")
        a["targets"] = find_targets(a)
    return amendments


def find_targets(a: dict) -> list[int]:
    instr = a["instruction"]
    if a["action"] == "Repealing" and "Part 14" in instr:
        return list(range(210, 229))  # Part 14 = Articles 210-228
    nums = []
    for m in ARTICLE_LIST.finditer(instr):
        group = re.sub(r"\(\d+\)", "", m.group(1))  # drop paragraph refs like 30(1)
        nums += [int(n) for n in re.findall(r"\d+", group)]
    nums += [int(n) for n in NUMBERED.findall(instr)]
    if not nums:  # e.g. "Adding two articles as follows:" -> numbers are in the body
        nums = [int(n) for n in BODY_HEADING.findall(a["text"])]
    return sorted(set(nums))


def apply_to_articles(articles: list[dict], amendments: list[dict]) -> None:
    by_num = {r["article_number"]: r for r in articles}
    for r in articles:
        r["status"], r["amendments"] = "original", []

    for a in amendments:  # the Appendix is in date order, so the last action wins
        instr = a["instruction"].lower()
        for n in a["targets"]:
            r = by_num.get(n)
            if r is None:
                print(f"WARNING: {a['id']} targets unknown article {n}")
                continue
            r["amendments"].append(a["id"])
            if a["action"] == "Adding" and " bis" in instr:
                pass  # a new "bis" article sits next to it; this one is unchanged
            elif a["action"] in ("Repealing", "Deleting") and "replacing it" not in instr:
                r["status"] = "repealed"
            elif a["action"] == "Adding" and "numbered" in instr:
                r["status"] = "replaced"
            else:
                r["status"] = "amended"


if __name__ == "__main__":
    lines = clean_lines(RAW_TXT.read_text(encoding="utf-8"))
    amendments = parse_appendix(lines)
    articles = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))
    apply_to_articles(articles, amendments)

    AMENDMENTS_JSON.write_text(json.dumps(amendments, ensure_ascii=False, indent=2), encoding="utf-8")
    ARTICLES_JSON.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- Sanity checks ----
    print(f"{len(amendments)} amendments parsed -> {AMENDMENTS_JSON}")
    no_target = [f"{a['id']}: {a['instruction'][:80]}" for a in amendments if not a["targets"]]
    print("No target found:", no_target or "none")
    print("Status counts:", dict(Counter(r["status"] for r in articles)))

    by_num = {r["article_number"]: r for r in articles}
    amd = {a["id"]: a for a in amendments}
    for n in (53, 75, 156, 210):
        r = by_num[n]
        print(f"\nArticle {n} [{r['status']}]")
        for aid in r["amendments"]:
            a = amd[aid]
            print(f"  {a['date']} {a['decree']}: {a['instruction'][:90]}")
    print("\nRepealed:", sorted(r["article_number"] for r in articles if r["status"] == "repealed"))