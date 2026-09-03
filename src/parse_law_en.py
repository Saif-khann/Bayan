"""Extract the official English Labor Law PDF and split it into one record per article."""
import json
import re
from pathlib import Path

from pypdf import PdfReader

PDF_PATH = Path("data/raw/labor_law_en.pdf")
RAW_TXT = Path("data/raw/labor_law_en.txt")
OUT_JSON = Path("data/processed/labor_law_en.json")

# A heading is a line containing ONLY "Article <number>", nothing else.
ARTICLE = re.compile(r"^Article\s+(\d+)$")
PART = re.compile(r"^Part \d+: ")
CHAPTER = re.compile(r"^Chapter \d+: ")
SECTION = re.compile(r"^(First|Second|Third): ")


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def clean_lines(text: str) -> list[str]:
    """Drop the running header and page numbers that repeat on every page."""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s == "Labor Law" or s.isdigit():
            continue
        lines.append(s)
    return lines


def split_articles(lines: list[str]) -> list[dict]:
    if "Appendix" not in lines:
        print("WARNING: no 'Appendix' line found, amendments may leak into articles")
    else:
        lines = lines[: lines.index("Appendix")]

    records, current = [], None
    part = chapter = section = None
    open_heading = None  # "part" or "chapter" while a heading may still be wrapping

    for s in lines:
        if not s:
            continue
        if PART.match(s):
            part, chapter, section = s, None, None
            open_heading, current = "part", None
            continue
        if CHAPTER.match(s):
            chapter, section = s, None
            open_heading, current = "chapter", None
            continue
        if SECTION.match(s):
            section = s
            open_heading, current = None, None
            continue

        m = ARTICLE.match(s)
        if m:
            open_heading = None
            current = {
                "id": f"labor_law-en-{m.group(1)}",
                "law": "labor_law",
                "lang": "en",
                "article_number": int(m.group(1)),
                "part": part,
                "chapter": chapter,
                "section": section,
                "lines": [],
            }
            records.append(current)
            continue

        # Not a heading and not an article start, so where does this line belong?
        if open_heading == "part":
            part += " " + s          # rest of a wrapped Part title
        elif open_heading == "chapter":
            chapter += " " + s       # rest of a wrapped Chapter title
        elif current is not None:
            current["lines"].append(s)

    for r in records:
        r["text"] = "\n".join(r.pop("lines"))
    return records


if __name__ == "__main__":
    text = extract_text(PDF_PATH)
    RAW_TXT.write_text(text, encoding="utf-8")  # keep it so you can inspect it

    records = split_articles(clean_lines(text))
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- Sanity checks ----
    numbers = [r["article_number"] for r in records]
    missing = sorted(set(range(1, 246)) - set(numbers))
    dupes = sorted({n for n in numbers if numbers.count(n) > 1})
    empty = [r["article_number"] for r in records if not r["text"]]

    print(f"{len(records)} articles -> {OUT_JSON}")
    print("Missing:", missing or "none")
    print("Duplicates:", dupes or "none")
    print("Empty:", empty or "none")
    by_num = {r["article_number"]: r for r in records}
    for n in (29, 64, 65, 121):
        r = by_num[n]
        print(f"\nArticle {n}")
        print(f"  part:    {r['part']}")
        print(f"  chapter: {r['chapter']}")
        print(f"  section: {r['section']}")
        print(f"  ends:    ...{r['text'][-80:]}")