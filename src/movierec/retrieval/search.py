"""Search & recommendation logic bridging retrieval layer to API schemas."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from statistics import mean

from movierec.api.schemas import (
    MovieRecommendation,
    ParticipantScore,
    RecommendationResponse,
)
from movierec.config import settings
from movierec.retrieval import Hit, Retriever

# --------------------------------------------------------------------------- aggregation
AggregationFn = Callable[[list[float]], float]


def aggregate_mean(scores: list[float]) -> float:
    """Default aggregation: arithmetic mean of participant scores."""
    return mean(scores) if scores else 0.0


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


def _hits_to_recommendations(hits: list[Hit]) -> list[MovieRecommendation]:
    """Convert retrieval Hits to API MovieRecommendation (single-participant scores)."""
    recs: list[MovieRecommendation] = []
    for hit in hits:
        recs.append(
            MovieRecommendation(
                id=str(hit.tmdb_id),
                **_payload_fields(hit.payload),
                group_score=hit.score,
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
def recommend_for_group(
    query_texts: list[str],
    top_k: int = 5,
    agg_fn: AggregationFn = aggregate_mean,
) -> RecommendationResponse:
    """
    Run retrieval for each participant, merge results, aggregate scores, return top picks.

    Args:
        query_texts: One natural-language query per participant.
        top_k: Total movies to return (top_pick + alternates).
        agg_fn: Function to aggregate per-participant scores into a group score.
                Defaults to arithmetic mean. Swappable for sum, max, etc.

    Returns:
        RecommendationResponse with top_pick and alternates (up to top_k - 1).
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

    retriever = _get_retriever()

    # Over-fetch per participant to have enough unique candidates after merging
    fetch_limit = max(top_k * 3, 10)
    all_hits_per_participant = retriever.search_many(query_texts, limit=fetch_limit)
    num_participants = len(all_hits_per_participant)

    # Merge by tmdb_id across participants
    # {tmdb_id: {participant_index: score, ...}}
    merged: dict[int, dict[int, float]] = defaultdict(dict)
    payload_cache: dict[int, dict] = {}

    for participant_idx, hits in enumerate(all_hits_per_participant):
        for hit in hits:
            merged[hit.tmdb_id][participant_idx] = hit.score
            # Cache payload from first occurrence (all participants return same movie data)
            if hit.tmdb_id not in payload_cache:
                payload_cache[hit.tmdb_id] = hit.payload

    # Build recommendations with aggregated scores
    recommendations: list[MovieRecommendation] = []
    for tmdb_id, participant_scores in merged.items():
        # Fill missing participant scores with 0.0
        for idx in range(num_participants):
            participant_scores.setdefault(idx, 0.0)

        # Extract all scores sorted by participant index
        scores_list = list(participant_scores.values())
        group_score = agg_fn(scores_list)

        individual_scores = [
            ParticipantScore(participant_index=idx, score=score)
            for idx, score in sorted(participant_scores.items())
        ]

        payload = payload_cache[tmdb_id]
        recommendations.append(
            MovieRecommendation(
                id=str(tmdb_id),
                **_payload_fields(payload),
                group_score=group_score,
                individual_scores=individual_scores,
            )
        )

    # Sort by group score descending
    recommendations.sort(key=lambda r: r.group_score, reverse=True)

    if not recommendations:
        # Fallback if retrieval returns nothing
        return RecommendationResponse(
            top_pick=MovieRecommendation(
                id="",
                title="No matches found",
                group_score=0.0,
            ),
            alternates=[],
        )

    top_pick = recommendations[0]
    alternates = recommendations[1:top_k]

    return RecommendationResponse(top_pick=top_pick, alternates=alternates)


# --------------------------------------------------------------------------- health / ready
def health_check() -> bool:
    """Qdrant reachable."""
    return _get_retriever().healthy()


def ready_check() -> bool:
    """Qdrant reachable AND collection exists with movies."""
    return _get_retriever().ready()
