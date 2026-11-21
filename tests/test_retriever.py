"""Tests for movierec.retrieval.retriever (embedder and store mocked)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from movierec.retrieval import retriever as rt
from movierec.retrieval.models import Hit, MovieDoc


@pytest.fixture
def r():
    embedder = MagicMock()
    embedder.embed_documents.side_effect = lambda texts: [[0.0]] * len(texts)
    store = MagicMock()
    store.client.get_collection.return_value.points_count = 0
    store.existing_ids.return_value = set()
    return rt.Retriever(embedder, store, upsert_batch_size=2)


def docs(n):
    return [MovieDoc(i, f"t{i}") for i in range(n)]


def test_chunks():
    assert [len(c) for c in rt._chunks(docs(5), 2)] == [2, 2, 1]


def test_index_batches_and_counts(r):
    r.store.client.get_collection.return_value.points_count = 10
    assert r.index(docs(5)) == 15
    assert r.store.upsert.call_count == 3


def test_index_skips_existing_docs(r):
    r.store.existing_ids.side_effect = [{0, 1}, set()]  # first batch fully stored
    assert r.index(docs(4)) == 2
    assert r.store.upsert.call_count == 1
    assert [d.tmdb_id for d in r.store.upsert.call_args.args[0]] == [2, 3]


def test_index_partial_batch_filtered(r):
    r.store.existing_ids.return_value = {0}
    r.index(docs(2))
    assert [d.tmdb_id for d in r.store.upsert.call_args.args[0]] == [1]
    r.embedder.embed_documents.assert_called_once_with(["t1"])


def test_reindex_does_not_check_existing(r):
    r.index(docs(2), skip_existing=False)
    r.store.existing_ids.assert_not_called()
    r.store.upsert.assert_called_once()


def test_search_embeds_and_filters(r):
    r.embedder.embed_queries.return_value = [[0.1]]
    r.store.search.return_value = [Hit(1, 0.5, {})]
    hits = r.search("q", limit=3, genres=["Drama"], year_min=2000, with_vectors=True)
    assert hits == r.store.search.return_value
    kwargs = r.store.search.call_args.kwargs
    assert kwargs["limit"] == 3 and kwargs["with_vectors"] is True
    assert kwargs["query_filter"] is not None


def test_search_vectors_one_result_list_per_vector(r):
    r.store.search.return_value = []
    out = r.search_vectors([[0.1], [0.2]])
    assert out == [[], []]
    assert r.store.search.call_args.kwargs["query_filter"] is None


@pytest.mark.parametrize(
    "healthy,exists,count,expected",
    [
        (True, True, 5, True),
        (False, True, 5, False),
        (True, False, 5, False),
        (True, True, 0, False),
    ],
)
def test_ready(r, healthy, exists, count, expected):
    r.store.healthy.return_value = healthy
    r.store.exists.return_value = exists
    r.store.count.return_value = count
    assert r.ready() is expected


def test_from_settings():
    s = SimpleNamespace(
        embed_model="org/Model.1",
        embed_cache_dir=Path("/tmp"),
        embed_batch_size=8,
        qdrant_url=":memory:",
        qdrant_collection_prefix="movies",
        upsert_batch_size=64,
    )
    with patch.object(rt, "Embedder") as emb, patch.object(rt, "QdrantStore") as store:
        emb.return_value.dim = 384
        obj = rt.Retriever.from_settings(s)
    emb.assert_called_once_with(
        model_name="org/Model.1", cache_dir=Path("/tmp"), batch_size=8
    )
    assert store.call_args.kwargs["collection"] == "movies__model-1"
    assert store.call_args.kwargs["dim"] == 384
    assert obj.upsert_batch_size == 64


def test_warmup_and_count_delegate(r):
    r.warmup()
    r.embedder.warmup.assert_called_once()
    r.store.count.return_value = 3
    assert r.count() == 3
