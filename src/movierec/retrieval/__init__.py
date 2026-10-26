"""Vector retrieval for movierec: fastembed embeddings stored and searched in Qdrant."""

from .data import MovieRecord, iter_movies, movie_to_payload, movie_to_text
from .embeddings import Embedder, EmbeddingBackend
from .retriever import Hit, MovieDoc, RetrievalSettings, Retriever
from .search import health_check, ready_check, recommend_for_group, search_movies
from .vectorstore import (
    CollectionMismatchError,
    CollectionNotFoundError,
    QdrantStore,
    build_filter,
    collection_name,
)

__all__ = [
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
    "build_filter",
    "collection_name",
    "health_check",
    "iter_movies",
    "movie_to_payload",
    "movie_to_text",
    "ready_check",
    "recommend_for_group",
    "search_movies",
]
