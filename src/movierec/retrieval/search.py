"""Search & recommendation logic bridging retrieval layer to API schemas."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Sequence

import numpy as np

from movierec.api.schemas import (
    MovieRecommendation,
    ParticipantScore,
    RecommendationResponse,
)
from movierec.config import settings
from movierec.retrieval import Hit, Retriever

# --------------------------------------------------------------------------- aggregation
AggregationFn = Callable[[Sequence[float]], float]


def aggregate_mean(scores: Sequence[float]) -> float:
    """Utilitarian / Average: maximizes overall group similarity."""
    return float(np.mean(scores)) if scores else 0.0


def aggregate_least_misery(scores: Sequence[float]) -> float:
    """Least Misery (Rawlsian): maximizes the lowest score so no one hates the pick."""
    return float(np.min(scores)) if scores else 0.0


def aggregate_most_pleasure(scores: Sequence[float]) -> float:
    """Most Pleasure: maximizes the highest individual score in the group."""
    return float(np.max(scores)) if scores else 0.0


def aggregate_nash(scores: Sequence[float]) -> float:
    """Nash Social Welfare (Geometric Mean): balances utility with fairness."""
    if not scores:
        return 0.0
    clamped = [max(float(s), 0.0) for s in scores]
    if any(s == 0.0 for s in clamped):
        return 0.0
    return float(math.exp(sum(math.log(s) for s in clamped) / len(clamped)))


def aggregate_fairness(scores: Sequence[float], penalty_weight: float = 0.5) -> float:
    """Fairness-Adjusted Mean (mean - lambda * std): penalizes disagreement."""
    if not scores:
        return 0.0
    arr = np.asarray(scores, dtype=np.float64)
    return float(np.mean(arr) - penalty_weight * np.std(arr))


def aggregate_approval(scores: Sequence[float], threshold: float = 0.5) -> float:
    """Approval Voting: fraction of participants >= threshold, broken by mean score."""
    if not scores:
        return 0.0
    arr = np.asarray(scores, dtype=np.float64)
    approval_rate = float(np.mean(arr >= threshold))
    tie_breaker = float(np.mean(arr)) * (0.1 / len(scores))
    return approval_rate + tie_breaker


AGGREGATION_STRATEGIES: dict[str, AggregationFn] = {
    "mean": aggregate_mean,
    "least_misery": aggregate_least_misery,
    "most_pleasure": aggregate_most_pleasure,
    "nash": aggregate_nash,
    "fairness": aggregate_fairness,
    "approval": aggregate_approval,
}

# --------------------------------------------------------------------------- retriever singleton
_retriever: Retriever | None = None
_retriever_lock = threading.Lock()


def _get_retriever() -> Retriever:
    """Lazy singleton Retriever; loads embedder on first use."""
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                _retriever = Retriever.from_settings(settings)
                _retriever.warmup()
    return _retriever


# --------------------------------------------------------------------------- hit → recommendation conversion
def _payload_fields(payload: dict) -> dict:
    """Movie details from a Qdrant payload, in MovieRecommendation's field names."""
    return {
        "title": payload.get("title", "Unknown"),
        "overview": payload.get("overview"),
        "year": payload.get("year"),
        "genres": payload.get("genres") or [],
        "poster_path": payload.get("poster_path"),
    }


def _hits_to_recommendations(
    hits: list[Hit],
    agg_fn: AggregationFn | None = None,
) -> list[MovieRecommendation]:
    """Convert retrieval Hits to API MovieRecommendation (single-participant scores)."""
    recs: list[MovieRecommendation] = []
    for hit in hits:
        group_score = agg_fn([hit.score]) if agg_fn is not None else hit.score
        recs.append(
            MovieRecommendation(
                id=str(hit.tmdb_id),
                **_payload_fields(hit.payload),
                group_score=group_score,
                individual_scores=[
                    ParticipantScore(participant_index=0, score=hit.score)
                ],
            )
        )
    return recs


# --------------------------------------------------------------------------- public API (placeholder for future searchbar)
def search_movies(query_text: str, top_k: int = 5) -> list[MovieRecommendation]:
    """Placeholder for future movie searchbar. Returns mock data."""
    # TODO: Replace with real retrieval when searchbar UI is added
    return [
        MovieRecommendation(
            id="101",
            title="Stub Movie: The Lion King",
            group_score=0.95,
            individual_scores=[ParticipantScore(participant_index=0, score=0.95)],
            overview="The circle of life...",
        )
    ]


# --------------------------------------------------------------------------- core group recommendation
def _cosine_similarity_matrix(
    query_vectors: np.ndarray,
    movie_vectors: np.ndarray,
) -> np.ndarray:
    """Compute exact cosine similarity for every (participant, pooled_movie) pair."""
    q_norms = np.linalg.norm(query_vectors, axis=1, keepdims=True)
    m_norms = np.linalg.norm(movie_vectors, axis=1, keepdims=True)

    q_normed = np.divide(
        query_vectors,
        q_norms,
        out=np.zeros_like(query_vectors, dtype=np.float64),
        where=q_norms > 0,
    )
    m_normed = np.divide(
        movie_vectors,
        m_norms,
        out=np.zeros_like(movie_vectors, dtype=np.float64),
        where=m_norms > 0,
    )
    return q_normed @ m_normed.T


def recommend_for_group(
    query_texts: list[str],
    top_k: int = 5,
    agg_fn: AggregationFn | str = aggregate_nash,
) -> RecommendationResponse:
    """
    Pool retrieved movies across all participants, compute cosine similarity for
    every query against all pooled movies, and rank via social choice aggregation.

    Args:
        query_texts: One natural-language query per participant.
        top_k: Total movies to return (top_pick + alternates).
        agg_fn: Aggregation callable or strategy name from AGGREGATION_STRATEGIES.

    Returns:
        RecommendationResponse with group_score and per-participant individual_scores.
    """
    if not query_texts:
        return RecommendationResponse(
            top_pick=MovieRecommendation(
                id="",
                title="No queries provided",
                group_score=0.0,
            ),
            alternates=[],
        )

    if isinstance(agg_fn, str):
        if agg_fn not in AGGREGATION_STRATEGIES:
            raise ValueError(
                f"Unknown aggregation strategy {agg_fn!r}. "
                f"Available: {list(AGGREGATION_STRATEGIES)}"
            )
        aggregator = AGGREGATION_STRATEGIES[agg_fn]
    else:
        aggregator = agg_fn

    retriever = _get_retriever()

    # SOLO: single participant needs no pooling, vector transfer, or matrix math
    if len(query_texts) == 1:
        hits = retriever.search(query_texts[0], limit=top_k)
        if not hits:
            return RecommendationResponse(
                top_pick=MovieRecommendation(
                    id="",
                    title="No matches found",
                    group_score=0.0,
                ),
                alternates=[],
            )
        recs = _hits_to_recommendations(hits, agg_fn=aggregator)
        return RecommendationResponse(top_pick=recs[0], alternates=recs[1:top_k])

    # GROUP: embed queries once and retrieve candidates with vectors
    query_vectors = retriever.embed_queries(query_texts)
    fetch_limit = max(top_k * 3, 10)
    all_hits_per_participant = retriever.search_vectors(
        query_vectors,
        limit=fetch_limit,
        with_vectors=True,
    )

    # Pool unique movies across all participants
    payload_cache: dict[int, dict] = {}
    vector_cache: dict[int, list[float]] = {}

    for hits in all_hits_per_participant:
        for hit in hits:
            if hit.tmdb_id not in payload_cache and hit.vector is not None:
                payload_cache[hit.tmdb_id] = hit.payload
                vector_cache[hit.tmdb_id] = hit.vector

    if not payload_cache:
        return RecommendationResponse(
            top_pick=MovieRecommendation(
                id="",
                title="No matches found",
                group_score=0.0,
            ),
            alternates=[],
        )

    pooled_ids = list(payload_cache.keys())

    # Compute cosine similarity between every query and all pooled movies
    query_matrix = np.asarray(query_vectors, dtype=np.float64)
    movie_matrix = np.asarray(
        [vector_cache[tmdb_id] for tmdb_id in pooled_ids], dtype=np.float64
    )
    # Shape: (num_participants, num_pooled_movies)
    similarity_matrix = _cosine_similarity_matrix(query_matrix, movie_matrix)

    # Aggregate scores and attach individual participant scores for the UI
    recommendations: list[MovieRecommendation] = []
    for movie_idx, tmdb_id in enumerate(pooled_ids):
        movie_scores = similarity_matrix[:, movie_idx].tolist()
        group_score = aggregator(movie_scores)

        individual_scores = [
            ParticipantScore(participant_index=p_idx, score=float(score))
            for p_idx, score in enumerate(movie_scores)
        ]

        recommendations.append(
            MovieRecommendation(
                id=str(tmdb_id),
                **_payload_fields(payload_cache[tmdb_id]),
                group_score=group_score,
                individual_scores=individual_scores,
            )
        )

    recommendations.sort(key=lambda r: r.group_score, reverse=True)

    top_pick = recommendations[0]
    alternates = recommendations[1:top_k]

    return RecommendationResponse(top_pick=top_pick, alternates=alternates)


# --------------------------------------------------------------------------- health / ready
def ready_check() -> bool:
    """Qdrant reachable AND collection exists with movies."""
    return _get_retriever().ready()
