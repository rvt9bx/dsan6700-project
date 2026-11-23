"""BM25 lexical baseline over movie overviews, shaped like Retriever.

Single-query and independent multi-query search mirror Retriever.search /
Retriever.search_vectors. `search_pooled` is the BM25 counterpart of the group flow:
pool every participant's candidates, then score *every* query against *every* pooled movie.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

import numpy as np
from loguru import logger
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

from .models import Hit
from .vectorstore import QdrantStore

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "he",
        "her",
        "his",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "she",
        "that",
        "the",
        "their",
        "them",
        "they",
        "this",
        "to",
        "was",
        "were",
        "which",
        "who",
        "will",
        "with",
    ]
)


def tokenize(text: str, remove_stopwords: bool = True) -> list[str]:
    """Lowercase alphanumeric tokens, optionally without common stopwords."""
    toks = _TOKEN_RE.findall((text or "").lower())
    return [t for t in toks if t not in _STOPWORDS] if remove_stopwords else toks


class BM25Retriever:
    """In-memory BM25 index. Build once, reuse (like the Retriever singleton in search.py)."""

    def __init__(
        self,
        docs: Iterable[tuple[int, dict]],
        text_field: str = "overview",
        remove_stopwords: bool = True,
        k1: float = 1.5,
        b: float = 0.75,
    ):
        """Index documents for BM25 search.

        Args:
            docs: (tmdb_id, payload) pairs, e.g. from QdrantStore.iter_payloads().
            text_field: Payload field that holds the text to index.
            remove_stopwords: Drop common words from documents and queries.
            k1: BM25 term-frequency saturation parameter.
            b: BM25 document-length normalisation parameter.
        """
        self.text_field = text_field
        self.remove_stopwords = remove_stopwords
        self.ids: list[int] = []
        self.payloads: list[dict] = []
        corpus: list[list[str]] = []
        for tmdb_id, payload in docs:
            self.ids.append(tmdb_id)
            self.payloads.append(payload)
            corpus.append(tokenize(payload.get(text_field, ""), remove_stopwords))
        if not corpus:
            raise ValueError("BM25Retriever got no documents")
        self.bm25 = BM25Okapi(corpus, k1=k1, b=b)
        logger.bind(movies=len(corpus)).info("Built BM25 index")

    # ---- constructors ------------------------------------------------
    @classmethod
    def from_store(cls, store: QdrantStore, **kwargs) -> BM25Retriever:
        """Index exactly what's in Qdrant, so both methods see the same corpus."""
        return cls(store.iter_payloads(), **kwargs)

    # ---- scoring helpers ---------------------------------------------
    def tokenize_queries(self, queries: Sequence[str]) -> list[list[str]]:
        """Tokenize queries the same way documents were tokenized."""
        return [tokenize(q, self.remove_stopwords) for q in queries]

    def score_matrix(self, queries: Sequence[str]) -> np.ndarray:
        """BM25 score of every query against every indexed movie.

        Returns:
            Array of shape (n_queries, n_movies), columns aligned with `self.ids`.
        """
        if not queries:
            return np.zeros((0, len(self.ids)), dtype=float)
        return np.vstack(
            [
                np.asarray(self.bm25.get_scores(toks), dtype=float)
                for toks in self.tokenize_queries(queries)
            ]
        )

    @staticmethod
    def _top_indices(row: np.ndarray, limit: int) -> np.ndarray:
        """Indices of the best `limit` movies with a positive score, best first."""
        top = np.argsort(-row, kind="stable")[:limit]
        return top[row[top] > 0]  # drop movies with no lexical overlap

    def _hit(self, index: int, score: float) -> Hit:
        return Hit(
            tmdb_id=self.ids[index], score=float(score), payload=self.payloads[index]
        )

    # ---- searching ---------------------------------------------------
    def search(self, query: str, limit: int = 10) -> list[Hit]:
        """Top movies for one natural-language query."""
        return self.search_many([query], limit)[0]

    def search_many(self, queries: Sequence[str], limit: int = 10) -> list[list[Hit]]:
        """Independent top-`limit` hits per query (same shape as Retriever.search_vectors).

        Each query is searched on its own, so use this for evaluation, not for groups.
        """
        scores = self.score_matrix(queries)
        return [
            [self._hit(i, row[i]) for i in self._top_indices(row, limit)]
            for row in scores
        ]

    def search_pooled(
        self,
        queries: Sequence[str],
        limit: int = 10,
        normalize: bool = True,
    ) -> list[list[Hit]]:
        """Pooled scoring for a group: one hit list per query over the SAME movies.

        1. Take each query's top-`limit` candidates and pool them (union).
        2. Score every query against every pooled movie, so a movie one participant
           found is scored for the others too instead of being filled with 0.
        3. Return, per query, all pooled movies sorted by that query's score
           (movies with no lexical overlap stay in with score 0).

        Args:
            queries: One query per participant.
            limit: Candidates contributed to the pool per query.
            normalize: Divide each query's scores by its best pooled score, giving
                values in [0, 1]. BM25 scores are unbounded and query-dependent, so
                aggregating raw scores across participants (mean, min, ...) would let
                long, keyword-rich queries dominate.
        """
        scores = self.score_matrix(queries)
        candidates = [self._top_indices(row, limit) for row in scores]
        if not any(len(c) for c in candidates):
            return [[] for _ in queries]

        pool = np.unique(np.concatenate(candidates))
        pooled = scores[:, pool]
        if normalize:
            peak = pooled.max(axis=1, keepdims=True)
            pooled = np.divide(pooled, peak, out=np.zeros_like(pooled), where=peak > 0)

        results: list[list[Hit]] = []
        for row in pooled:
            order = np.argsort(-row, kind="stable")
            results.append([self._hit(int(pool[k]), row[k]) for k in order])
        return results
