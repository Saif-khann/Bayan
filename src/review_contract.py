"""Review an employment contract clause by clause against the Saudi Labor Law."""
import json
import re
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types

from answer import generate
from hybrid import HybridSearch

REVIEW_PROMPT = """You are reviewing ONE clause of an employment contract against the Saudi Labor Law.

Rules:
1. Use ONLY the articles below. Amendments are listed in date order after each article;
   the LATEST amendment is the law in force.
2. Use the contract context (parties, nationality) when it matters.
3. "status" must be one of:
   - "violation": the clause conflicts with an article (e.g. gives the worker less than the
     law guarantees, or puts a cost on the worker that the law puts on the employer).
   - "compliant": the clause is consistent with the articles, or they don't restrict it.
     A clause giving the worker MORE than the law requires is compliant.
   - "needs_review": the articles are not enough to decide.
4. "articles": the article numbers your decision relies on. For added articles such as "79 bis", cite the base number (79).
5. "issue": one sentence explaining the problem ("" if compliant).
6. "suggested_fix": a corrected version of the clause ("" if compliant).

Return JSON only, in this exact shape:
{{"status": "...", "articles": [], "issue": "...", "suggested_fix": "..."}}

CONTRACT CONTEXT:
{preamble}

ARTICLES:
{context}

CLAUSE:
{clause}
"""

CLAUSE_START = re.compile(r"^(\d+)\.\s+", re.MULTILINE)


def split_clauses(text: str) -> tuple[str, list[dict]]:
    parts = CLAUSE_START.split(text)  # [preamble, num, text, num, text, ...]
    preamble = parts[0].strip()
    clauses = [{"number": int(parts[i]), "text": parts[i + 1].strip()} for i in range(1, len(parts), 2)]
    return preamble, clauses


def review_clause(clause: dict, preamble: str, engine: HybridSearch, client: genai.Client) -> dict:
    results = engine.search(clause["text"], k=6)
    context = "\n\n---\n\n".join(d["content"] for _, d in results)
    prompt = REVIEW_PROMPT.format(preamble=preamble, context=context, clause=clause["text"])
    config = types.GenerateContentConfig(response_mime_type="application/json")
    raw, model = generate(client, prompt, config=config)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"status": "needs_review", "articles": [], "issue": "Model returned invalid JSON.", "suggested_fix": ""}
    result["articles"] = [int(a) for a in result.get("articles", []) if str(a).isdigit()]
    result["retrieved"] = [d["article_number"] for _, d in results]
    result["model"] = model
    return result


def score(reviews: dict, expected: dict) -> None:
    caught = cited = false_alarms = 0
    for n, r in reviews.items():
        if n in expected:
            if r["status"] == "violation":
                caught += 1
                cited += bool(set(r["articles"]) & set(expected[n]))
            else:
                print(f"  MISSED clause {n}: got {r['status']}, expected violation of {expected[n]}")
        elif r["status"] == "violation":
            false_alarms += 1
            print(f"  FALSE ALARM clause {n}: {r.get('issue')}")
    clean = len(reviews) - len(expected)
    print("\n" + "=" * 80)
    print(f"Violations caught: {caught}/{len(expected)}   (citing the right article: {cited}/{len(expected)})")
    print(f"False alarms on legal clauses: {false_alarms}/{clean}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/contracts/sample_contract_en.txt")
    preamble, clauses = split_clauses(path.read_text(encoding="utf-8"))
    client, engine = genai.Client(), HybridSearch()

    reviews = {}
    for c in clauses:
        r = review_clause(c, preamble, engine, client)
        reviews[c["number"]] = r
        print(f"\nClause {c['number']}: [{r['status'].upper()}] cites {r['articles']}   (retrieved {r['retrieved']})")
        print(f"  {c['text'][:100]}")
        if r["status"] != "compliant":
            print(f"  Issue: {r.get('issue')}")
            print(f"  Fix:   {r.get('suggested_fix')}")
        time.sleep(3)  # free-tier rate limit

    out = path.with_suffix(".review.json")
    out.write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved -> {out}")
    expected_path = path.with_suffix(".expected.json")
    if expected_path.exists():
        expected = {int(k): v for k, v in json.loads(expected_path.read_text(encoding="utf-8")).items()}
        score(reviews, expected)