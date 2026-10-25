"""Qdrant wrapper. This is the only module that imports qdrant_client."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from qdrant_client import QdrantClient, models

from .models import Hit, MovieDoc

logger = logging.getLogger(__name__)


class CollectionMismatchError(RuntimeError):
    """The existing collection was built with a different vector size."""


class CollectionNotFoundError(RuntimeError):
    """The collection doesn't exist yet (ingest hasn't been run for this model)."""


def collection_name(prefix: str, model_name: str) -> str:
    """Name the collection after the embedding model.

    'BAAI/bge-small-en-v1.5' -> 'movies__bge-small-en-v1-5'
    Changing EMBED_MODEL therefore creates a fresh collection instead of
    mixing incompatible vectors in the old one.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", model_name.split("/")[-1]).strip("-").lower()
    return f"{prefix}__{slug}"


def build_filter(
    genres: Sequence[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
) -> models.Filter | None:
    """Turn simple search options into a Qdrant payload filter."""
    must: list[models.Condition] = []
    if genres:
        must.append(
            models.FieldCondition(key="genres", match=models.MatchAny(any=list(genres)))
        )
    if year_min is not None or year_max is not None:
        must.append(
            models.FieldCondition(
                key="year", range=models.Range(gte=year_min, lte=year_max)
            )
        )
    return models.Filter(must=must) if must else None


class QdrantStore:
    def __init__(
        self,
        url: str,
        collection: str,
        dim: int,
        client: QdrantClient | None = None,
        timeout: int = 30,
    ):
        self.collection = collection
        self.dim = dim
        if client is not None:
            self.client = client
        elif url == ":memory:":
            self.client = QdrantClient(":memory:")
        elif url == "qdrant":
            self.client = QdrantClient(path=url)
        else:
            self.client = QdrantClient(url=url, timeout=timeout)
        self._local = url == ":memory:"
        self._known_to_exist = False

    # ---- collection management ---------------------------------------
    def exists(self) -> bool:
        return self.client.collection_exists(self.collection)

    def ensure_collection(self) -> None:
        """Create the collection if missing; otherwise verify its vector size."""
        if not self.exists():
            logger.info(
                "Creating collection %s (dim=%d, cosine)", self.collection, self.dim
            )
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=self.dim, distance=models.Distance.COSINE
                ),
            )
            self._create_payload_indexes()
        else:
            self._check_dim()
        self._known_to_exist = True

    def _create_payload_indexes(self) -> None:
        # Speeds up filtered search on large collections (no effect in in-memory mode).
        if self._local:
            return
        for field, schema in (
            ("genres", models.PayloadSchemaType.KEYWORD),
            ("year", models.PayloadSchemaType.INTEGER),
        ):
            self.client.create_payload_index(
                self.collection, field_name=field, field_schema=schema
            )

    def _check_dim(self) -> None:
        params = self.client.get_collection(self.collection).config.params
        vectors = params.vectors
        size = getattr(vectors, "size", None)
        if size is not None and size != self.dim:
            raise CollectionMismatchError(
                f"Collection {self.collection!r} has vector size {size}, but the current "
                f"embedding model produces {self.dim}. Use a new collection name or re-ingest."
            )

    def require_collection(self) -> None:
        """Cheap guard for search-only callers (the app): fail clearly if ingest hasn't run."""
        if self._known_to_exist:
            return
        if not self.exists():
            raise CollectionNotFoundError(
                f"Collection {self.collection!r} does not exist. Run the ingest job first."
            )
        self._check_dim()
        self._known_to_exist = True

    # ---- writes ------------------------------------------------------
    def existing_ids(self, ids: Sequence[int], chunk: int = 1000) -> set[int]:
        """Which of these ids are already stored? (used to skip re-embedding)"""
        found: set[int] = set()
        for i in range(0, len(ids), chunk):
            records = self.client.retrieve(
                self.collection,
                ids=list(ids[i : i + chunk]),
                with_payload=False,
                with_vectors=False,
            )
            found.update(int(r.id) for r in records)
        return found

    def upsert(
        self, docs: Sequence[MovieDoc], vectors: Sequence[Sequence[float]]
    ) -> None:
        if len(docs) != len(vectors):
            raise ValueError(f"{len(docs)} docs but {len(vectors)} vectors")
        points = [
            models.PointStruct(id=d.tmdb_id, vector=list(v), payload=d.payload)
            for d, v in zip(docs, vectors)
        ]
        self.client.upsert(self.collection, points=points, wait=True)

    # ---- reads -------------------------------------------------------
    def search(
        self,
        vector: Sequence[float],
        limit: int = 10,
        query_filter: models.Filter | None = None,
    ) -> list[Hit]:
        self.require_collection()
        result = self.client.query_points(
            self.collection,
            query=list(vector),
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )
        return [
            Hit(tmdb_id=int(p.id), score=float(p.score), payload=dict(p.payload or {}))
            for p in result.points
        ]

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    def healthy(self) -> bool:
        """True if the Qdrant server answers (used by /health)."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            logger.exception("Qdrant health check failed")
            return False
