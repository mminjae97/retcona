"""Embedding wrapper (design doc chapter 5).

Hybrid of KURE-v1 (semantic) + BM25 (keyword matching).
Narrows down relevant past episode manuscripts/settings via vector similarity
search (sqlite-vec), then reranks the final Top-K with the cross-encoder in
ai/reranker.py.
"""

# TODO: KURE-v1 exported to ONNX (ml/export_onnx.py), run like the other models; a BM25 index with rank_bm25.BM25Okapi


def embed(text: str) -> list[float]:
    raise NotImplementedError


def bm25_score(query: str, corpus: list[str]) -> list[float]:
    raise NotImplementedError
