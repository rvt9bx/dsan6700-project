"""The one class the rest of movierec uses for indexing and searching."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import islice

from loguru import logger

from .embeddings import Embedder, EmbeddingBackend
from .models import Hit, MovieDoc, RetrievalSettings
from .vectorstore import QdrantStore, build_filter, collection_name


# ---------------------------------------------------------------- helpers
def _chunks(items: Iterable[MovieDoc], size: int) -> Iterator[list[MovieDoc]]:
    """Yield an iterable of movie documents in batches of the given size.

    Args:
        items: Documents to divide into batches.
        size: Maximum number of documents per batch.
    """
    it = iter(items)
    while chunk := list(islice(it, size)):
        yield chunk


# ---------------------------------------------------------------- QueryFilter
@dataclass(frozen=True)
class QueryFilter:
    """One person's metadata filter, applied to their own retrieval only."""

    genres: tuple[str, ...] = ()
    year_min: int | None = None
    year_max: int | None = None

    @property
    def active(self) -> bool:
        """True if this filter restricts anything."""
        return (
            bool(self.genres) or self.year_min is not None or self.year_max is not None
        )


# ---------------------------------------------------------------- Retriever
class Retriever:
    """Coordinate movie indexing, embedding, and similarity search."""

    def __init__(
        self,
        embedder: EmbeddingBackend,
        store: QdrantStore,
        upsert_batch_size: int = 256,
    ):
        """Initialize a retriever with an embedding backend and vector store.

        Args:
            embedder: Backend used to create document and query embeddings.
            store: Vector store used to index and search documents.
            upsert_batch_size: Maximum number of documents indexed per batch.
        """
        self.embedder = embedder
        self.store = store
        self.upsert_batch_size = upsert_batch_size

    @classmethod
    def from_settings(cls, settings: RetrievalSettings) -> Retriever:
        """Build everything from the project settings object."""
        embedder = Embedder(
            model_name=settings.embed_model,
            cache_dir=settings.embed_cache_dir,
            batch_size=settings.embed_batch_size,
        )
        store = QdrantStore(
            url=settings.qdrant_url,
            collection=collection_name(
                settings.qdrant_collection_prefix, settings.embed_model
            ),
            dim=embedder.dim,
        )
        return cls(embedder, store, upsert_batch_size=settings.upsert_batch_size)

    # ---- indexing (ingest job) ---------------------------------------
    def index(self, docs: Iterable[MovieDoc], skip_existing: bool = True) -> int | None:
        """Embed and store movies. Returns how many were newly indexed."""
        indexed = (
            self.store.client.get_collection(self.store.collection).points_count or 0
        )
        for chunk in _chunks(docs, self.upsert_batch_size):
            if skip_existing:
                ids_to_check = [d.tmdb_id for d in chunk]
                existing = self.store.existing_ids(ids_to_check, len(chunk))

                if existing:
                    # Filter chunk down to only docs whose tmdb_id is NOT in existing
                    chunk = [d for d in chunk if d.tmdb_id not in existing]

                    # If all docs in this chunk already exist, skip to the next batch
                    if not chunk:
                        continue

            # Extract texts for embedding from the filtered chunk
            texts = [d.text for d in chunk]

            # Embed and upsert only the non-existing documents
            vectors = self.embedder.embed_documents(texts)
            self.store.upsert(chunk, vectors)

            indexed += len(chunk)
            logger.bind(new=len(chunk), total=indexed).info("Indexed batch")
        return indexed

    # ---- searching (app) ---------------------------------------------
    def embed_queries(self, queries: Sequence[str]) -> list[list[float]]:
        """Embed user queries into dense vectors."""
        return self.embedder.embed_queries(queries)

    def search_vectors(
        self,
        vectors: Sequence[Sequence[float]],
        limit: int = 10,
        filters: Sequence[QueryFilter] | None = None,
        with_vectors: bool = False,
    ) -> list[list[Hit]]:
        """Search Qdrant using pre-computed query vectors and optional per-vector filters."""
        if filters is not None and len(filters) != len(vectors):
            raise ValueError("filters must have one entry per vector")

        results = []
        for i, vector in enumerate(vectors):
            query_filter = None
            if filters is not None:
                f = filters[i]
                query_filter = build_filter(f.genres, f.year_min, f.year_max)

            results.append(
                self.store.search(
                    vector,
                    limit=limit,
                    query_filter=query_filter,
                    with_vectors=with_vectors,
                )
            )
        return results

    def search(
        self,
        query: str,
        limit: int = 10,
        genres: Sequence[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        with_vectors: bool = False,
    ) -> list[Hit]:
        """Search for movies using a natural-language query and optional metadata filters."""
        vectors = self.embed_queries([query])

        query_filter = QueryFilter(
            genres=tuple(genres or ()),
            year_min=year_min,
            year_max=year_max,
        )

        return self.search_vectors(
            vectors,
            limit=limit,
            filters=[query_filter],
            with_vectors=with_vectors,
        )[0]

    # ---- status (health / ready endpoints) ---------------------------
    def healthy(self) -> bool:
        """Qdrant reachable."""
        return self.store.healthy()

    def ready(self) -> bool:
        """Qdrant reachable AND the collection has movies in it."""
        return self.store.healthy() and self.store.exists() and self.store.count() > 0

    def count(self) -> int:
        """Return the number of movies stored in the vector collection."""
        return self.store.count()

    def warmup(self) -> None:
        """Load the model now (call from FastAPI startup)."""
        self.embedder.warmup()
