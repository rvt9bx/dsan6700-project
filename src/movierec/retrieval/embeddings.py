"""Embedding model wrapper built on fastembed.

The model name and the weights cache directory both come from settings, so
swapping models is a config change and the weights can live on a Docker volume.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class EmbeddingBackend(Protocol):
    """What the Retriever needs from an embedder (lets tests use a fake)."""

    model_name: str

    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]: ...

    def warmup(self) -> None: ...


class Embedder:
    """fastembed model loaded lazily, once per process."""

    def __init__(self, model_name: str, cache_dir: str | Path, batch_size: int = 64):
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.batch_size = batch_size
        self._model = None
        self._dim: int | None = None

    # ---- model lookup -------------------------------------------------
    @staticmethod
    def _supported() -> dict[str, dict]:
        from fastembed import TextEmbedding

        return {m["model"]: m for m in TextEmbedding.list_supported_models()}

    def _check_supported(self) -> dict:
        supported = self._supported()
        if self.model_name not in supported:
            examples = ", ".join(sorted(supported)[:8])
            raise ValueError(
                f"Unknown embedding model {self.model_name!r}. "
                f"Set EMBED_MODEL to a fastembed-supported model, e.g. {examples}, ..."
            )
        return supported[self.model_name]

    # ---- properties ---------------------------------------------------
    @property
    def dim(self) -> int:
        """Vector size. Read from fastembed's model list, so no weights download needed."""
        if self._dim is None:
            self._dim = int(self._check_supported()["dim"])
        return self._dim

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._check_supported()
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Loading embedding model %s (cache: %s)",
                self.model_name,
                self.cache_dir,
            )
            self._model = TextEmbedding(
                model_name=self.model_name, cache_dir=str(self.cache_dir)
            )
        return self._model

    def warmup(self) -> None:
        """Load the model now (call at app startup so the first request isn't slow)."""
        _ = self.model

    # ---- embedding ----------------------------------------------------
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed movie text (stored side)."""
        if not texts:
            return []
        vecs = self.model.passage_embed(list(texts), batch_size=self.batch_size)
        return [v.tolist() for v in vecs]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed user text (query side). Uses the model's query handling."""
        if not texts:
            return []
        vecs = self.model.query_embed(list(texts), batch_size=self.batch_size)
        return [v.tolist() for v in vecs]
