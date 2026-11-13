"""Vector retrieval for movierec: fastembed embeddings stored and searched in Qdrant."""

from .data import MovieRecord, iter_movies, movie_to_payload, movie_to_text
from .embeddings import Embedder, EmbeddingBackend
from .retriever import Hit, MovieDoc, RetrievalSettings, Retriever
from .search import (
    AGGREGATION_STRATEGIES,
    aggregate_approval,
    aggregate_fairness,
    aggregate_least_misery,
    aggregate_mean,
    aggregate_most_pleasure,
    aggregate_nash,
    ready_check,
    recommend_for_group,
    search_movies,
)
from .vectorstore import (
    CollectionMismatchError,
    CollectionNotFoundError,
    QdrantStore,
    build_filter,
    collection_name,
)

__all__ = [
    "AGGREGATION_STRATEGIES",
    "CollectionMismatchError",
    "CollectionNotFoundError",
    "Embedder",
    "EmbeddingBackend",
    "Hit",
    "MovieDoc",
    "MovieRecord",
    "QdrantStore",
    "RetrievalSettings",
    "Retriever",
    "aggregate_approval",
    "aggregate_fairness",
    "aggregate_least_misery",
    "aggregate_mean",
    "aggregate_most_pleasure",
    "aggregate_nash",
    "build_filter",
    "collection_name",
    "iter_movies",
    "movie_to_payload",
    "movie_to_text",
    "ready_check",
    "recommend_for_group",
    "search_movies",
]
