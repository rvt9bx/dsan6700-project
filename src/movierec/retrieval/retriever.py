"""The one class the rest of movierec uses for indexing and searching."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from itertools import islice

from .embeddings import Embedder, EmbeddingBackend
from .models import Hit, MovieDoc, RetrievalSettings
from .vectorstore import QdrantStore, build_filter, collection_name

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- helpers
def _chunks(items: Iterable[MovieDoc], size: int) -> Iterator[list[MovieDoc]]:
    it = iter(items)
    while chunk := list(islice(it, size)):
        yield chunk


# ---------------------------------------------------------------- Retriever
class Retriever:
    def __init__(
        self,
        embedder: EmbeddingBackend,
        store: QdrantStore,
        upsert_batch_size: int = 256,
    ):
        self.embedder = embedder
        self.store = store
        self.upsert_batch_size = upsert_batch_size

    @classmethod
    def from_settings(cls, settings: RetrievalSettings) -> Retriever:
        """Build everything from your project settings object."""
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
            logger.info("Indexed batch: %d new (total %d)", len(chunk), indexed)
        return indexed

    # ---- searching (app) ---------------------------------------------
    def search(
        self,
        query: str,
        limit: int = 10,
        genres: Sequence[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[Hit]:
        """Natural-language query in, ranked movies out."""
        return self.search_many([query], limit, genres, year_min, year_max)[0]

    def search_many(
        self,
        queries: Sequence[str],
        limit: int = 10,
        genres: Sequence[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[list[Hit]]:
        """One hit list per query (embeds all queries in one batch). Used for groups."""
        vectors = self.embedder.embed_queries(queries)
        flt = build_filter(genres, year_min, year_max)
        return [self.store.search(v, limit=limit, query_filter=flt) for v in vectors]

    # ---- status (health / ready endpoints) ---------------------------
    def healthy(self) -> bool:
        """Qdrant reachable."""
        return self.store.healthy()

    def ready(self) -> bool:
        """Qdrant reachable AND the collection has movies in it."""
        return self.store.healthy() and self.store.exists() and self.store.count() > 0

    def count(self) -> int:
        return self.store.count()

    def warmup(self) -> None:
        """Load the model now (call from FastAPI startup)."""
        self.embedder.warmup()
