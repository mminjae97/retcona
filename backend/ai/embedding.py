"""임베딩 래퍼 (설계서 5장).

KURE-v1(의미 기반) + BM25(키워드 매칭) 하이브리드.
과거 화 원고/설정 중 관련 있는 것을 pgvector 유사도 검색으로 추린 뒤,
ai/reranker.py의 cross-encoder로 최종 Top-K를 정렬한다.
"""

# TODO: sentence-transformers로 KURE-v1 로드, rank_bm25.BM25Okapi 로 BM25 인덱스 구성


def embed(text: str) -> list[float]:
    raise NotImplementedError


def bm25_score(query: str, corpus: list[str]) -> list[float]:
    raise NotImplementedError
