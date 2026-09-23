"""Hybrid search: BM25 + embeddings via Reciprocal Rank Fusion, plus direct article lookup."""
import re

from search_bm25 import BM25Search, build_documents
from search_embed import EmbeddingSearch

# Matches "Article 109", "article 52", "المادة 109", "المادة (١٠٩)"
ARTICLE_REF = re.compile(r"(?:\barticle|المادة)\s*\(?\s*([0-9٠-٩]+)", re.IGNORECASE)


class HybridSearch:
    def __init__(self, rrf_k: int = 60, depth: int = 20):
        self.bm25 = BM25Search(build_documents())
        self.embed = EmbeddingSearch()
        self.by_num = {d["article_number"]: d for d in self.bm25.docs}  # full text + amendments
        self.rrf_k, self.depth = rrf_k, depth

    def search(self, query: str, k: int = 5) -> list[tuple[float, dict]]:
        scores = {}
        for engine in (self.bm25, self.embed):
            for rank, (_, d) in enumerate(engine.search(query, k=self.depth), start=1):
                n = d["article_number"]
                scores[n] = scores.get(n, 0) + 1 / (self.rrf_k + rank)

        for m in ARTICLE_REF.finditer(query):  # explicit citation -> put it first
            n = int(m.group(1))  # int() also understands Arabic digits like ١٠٩
            if n in self.by_num:
                scores[n] = scores.get(n, 0) + 1.0

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
        return [(s, self.by_num[n]) for n, s in ranked]