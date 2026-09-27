"""Score BM25, embeddings, and hybrid side by side."""
from evaluate import run_tests
from hybrid import HybridSearch

h = HybridSearch()  # loads both engines once
for name, engine in [("BM25", h.bm25), ("Embeddings", h.embed), ("Hybrid", h)]:
    print(f"\n=== {name} ===")
    run_tests(engine)