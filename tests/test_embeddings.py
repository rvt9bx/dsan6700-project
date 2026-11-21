"""Tests for movierec.retrieval.embeddings (fastembed is faked; no weights needed)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from movierec.retrieval.embeddings import Embedder

MODEL = "BAAI/bge-small-en-v1.5"


@pytest.fixture
def te(monkeypatch):
    """Fake fastembed.TextEmbedding, installed in sys.modules so the real package isn't needed."""
    te = MagicMock()
    te.list_supported_models.return_value = [
        {"model": MODEL, "dim": 384},
        {"model": "other/model", "dim": 768},
    ]
    te.return_value.passage_embed.return_value = [
        np.array([0.1, 0.2]),
        np.array([0.3, 0.4]),
    ]
    te.return_value.query_embed.return_value = [np.array([0.5, 0.6])]
    fake = types.ModuleType("fastembed")
    fake.TextEmbedding = te
    monkeypatch.setitem(sys.modules, "fastembed", fake)
    return te


@pytest.fixture
def embedder(te, tmp_path):
    return Embedder(MODEL, tmp_path / "cache", batch_size=128)


def test_init_stores_config(tmp_path):
    e = Embedder(MODEL, str(tmp_path), batch_size=8)
    assert e.cache_dir == Path(tmp_path) and e.batch_size == 8


def test_dim_reads_model_list_without_loading_weights(embedder, te):
    assert embedder.dim == 384
    assert embedder.dim == 384  # cached
    te.list_supported_models.assert_called_once()
    te.assert_not_called()


def test_unsupported_model_raises_on_dim_and_load(te, tmp_path):
    e = Embedder("unsupported/model", tmp_path)
    with pytest.raises(ValueError, match="Unknown embedding model"):
        _ = e.dim
    with pytest.raises(ValueError, match="Unknown embedding model"):
        e.warmup()
    te.assert_not_called()


def test_warmup_loads_once_and_creates_cache_dir(embedder, te):
    embedder.warmup()
    embedder.warmup()
    te.assert_called_once_with(model_name=MODEL, cache_dir=str(embedder.cache_dir))
    assert embedder.cache_dir.is_dir()


def test_embed_documents_lazy_loads_and_converts_to_lists(embedder, te):
    te.assert_not_called()
    assert embedder.embed_documents(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]
    te.return_value.passage_embed.assert_called_once_with(["a", "b"], batch_size=128)


def test_embed_queries_uses_query_side(embedder, te):
    assert embedder.embed_queries(["q"]) == [[0.5, 0.6]]
    te.return_value.query_embed.assert_called_once_with(["q"], batch_size=128)
    te.return_value.passage_embed.assert_not_called()


@pytest.mark.parametrize("method", ["embed_documents", "embed_queries"])
def test_empty_input_returns_empty_without_loading_model(embedder, te, method):
    assert getattr(embedder, method)([]) == []
    te.assert_not_called()
