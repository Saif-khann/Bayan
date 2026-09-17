"""Keyword search (BM25) over the Labor Law articles, including their amendments."""
import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

ARTICLES_JSON = Path("data/processed/labor_law_en.json")
AMENDMENTS_JSON = Path("data/processed/labor_law_en_amendments.json")

# Words so common in this law that they carry no meaning for search
STOPWORDS = {
    "the", "of", "and", "to", "a", "in", "for", "or", "by", "be", "shall", "this",
    "law", "any", "is", "on", "as", "with", "his", "he", "that", "may", "it", "such",
    "an", "from", "at", "which", "not", "if", "its", "their", "them", "who", "are",
    "has", "have",
}


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS]


def build_documents() -> list[dict]:
    articles = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))
    amendments = {a["id"]: a for a in json.loads(AMENDMENTS_JSON.read_text(encoding="utf-8"))}

    docs = []
    for r in articles:
        if r["status"] == "repealed":
            continue  # never retrieve dead law
        parts = [f"Article {r['article_number']}", r["part"], r["chapter"], r["section"], r["text"]]
        for aid in r["amendments"]:  # in date order, so the latest wording comes last
            a = amendments[aid]
            parts.append(f"Amendment ({a['date']}, Royal Decree {a['decree']}): {a['instruction']}\n{a['text']}")
        docs.append({
            "id": r["id"],
            "article_number": r["article_number"],
            "status": r["status"],
            "content": "\n".join(p for p in parts if p),
        })
    return docs


class BM25Search:
    def __init__(self, docs: list[dict]):
        self.docs = docs
        self.bm25 = BM25Okapi([tokenize(d["content"]) for d in docs])

    def search(self, query: str, k: int = 5) -> list[tuple[float, dict]]:
        scores = self.bm25.get_scores(tokenize(query))
        ranked = sorted(zip(scores, self.docs), key=lambda x: x[0], reverse=True)
        return [(float(s), d) for s, d in ranked[:k] if s > 0]


if __name__ == "__main__":
    from evaluate import run_tests
    engine = BM25Search(build_documents())
    print(f"Indexed {len(engine.docs)} articles")
    run_tests(engine)