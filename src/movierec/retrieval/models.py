"""Plain data types shared across the retrieval module."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class MovieDoc:
    """One movie ready to be embedded and stored.

    tmdb_id:      stable movie id (used as the Qdrant point id, so re-indexing is idempotent)
    text:    the exact string that gets embedded (built elsewhere, e.g. by data code)
    payload: metadata stored next to the vector (title, year, genres, ...)
    """

    tmdb_id: int
    text: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Hit:
    """One search result."""

    tmdb_id: int
    score: float
    payload: dict[str, Any]


class RetrievalSettings(Protocol):
    """The fields the retrieval module reads from your project settings."""

    embed_model: str
    embed_cache_dir: Path
    embed_batch_size: int
    qdrant_url: str
    qdrant_collection_prefix: str
    upsert_batch_size: int
