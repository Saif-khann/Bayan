"""Meaning-based search with multilingual embeddings."""
import hashlib
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from search_bm25 import AMENDMENTS_JSON, ARTICLES_JSON

MODEL_NAME = "intfloat/multilingual-e5-base"
CACHE = Path("data/processed/embeddings_en.npz")


def build_chunks() -> list[dict]:
    articles = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))
    amendments = {a["id"]: a for a in json.loads(AMENDMENTS_JSON.read_text(encoding="utf-8"))}

    chunks = []
    for r in articles:
        if r["status"] == "repealed":
            continue
        head = f"Article {r['article_number']}. {r['chapter'] or r['part'] or ''}"
        base = {"article_number": r["article_number"], "status": r["status"]}
        chunks.append({**base, "text": f"{head}\n{r['text']}"})
        for aid in r["amendments"]:
            a = amendments[aid]
            chunks.append({**base, "text": f"{head} (amended {a['date']})\n{a['instruction']}\n{a['text']}"})
    return chunks


class EmbeddingSearch:
    def __init__(self):
        self.model = SentenceTransformer(MODEL_NAME)
        self.chunks = build_chunks()
        texts = ["passage: " + c["text"] for c in self.chunks]  # e5 needs this prefix

        # Cache: only re-embed if the texts changed
        key = hashlib.md5("\n".join(texts).encode("utf-8")).hexdigest()
        self.vectors = None
        if CACHE.exists():
            data = np.load(CACHE)
            if str(data["key"]) == key:
                self.vectors = data["vectors"]
        if self.vectors is None:
            self.vectors = self.model.encode(
                texts, normalize_embeddings=True, batch_size=16, show_progress_bar=True
            )
            np.savez(CACHE, vectors=self.vectors, key=key)

    def search(self, query: str, k: int = 5) -> list[tuple[float, dict]]:
        q = self.model.encode(["query: " + query], normalize_embeddings=True)[0]
        sims = self.vectors @ q  # cosine similarity, since vectors are normalized

        best = {}  # article_number -> (score, chunk): keep each article's best chunk
        for sim, c in zip(sims, self.chunks):
            n = c["article_number"]
            if n not in best or sim > best[n][0]:
                best[n] = (float(sim), c)
        ranked = sorted(best.values(), key=lambda x: x[0], reverse=True)[:k]
        return [(s, {"article_number": c["article_number"], "status": c["status"]}) for s, c in ranked]


if __name__ == "__main__":
    from evaluate import run_tests
    engine = EmbeddingSearch()
    print(f"Embedded {len(engine.chunks)} chunks")
    run_tests(engine)