"""Embedding wrapper (design doc chapter 5).

Hybrid of KURE-v1 (semantic) + BM25 (keyword matching).
Narrows down relevant past episode manuscripts/settings via pgvector similarity
search, then reranks the final Top-K with the cross-encoder in ai/reranker.py.
"""

# TODO: load KURE-v1 via sentence-transformers, build a BM25 index with rank_bm25.BM25Okapi


def embed(text: str) -> list[float]:
    raise NotImplementedError


def bm25_score(query: str, corpus: list[str]) -> list[float]:
    raise NotImplementedError
