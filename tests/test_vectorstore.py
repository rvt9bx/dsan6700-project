"""Tests for movierec.retrieval.vectorstore (Qdrant fully mocked)."""

from unittest.mock import MagicMock, patch

import pytest

from movierec.retrieval import vectorstore as vs
from movierec.retrieval.models import MovieDoc


def make_store(url="http://x", dim=3, client=None):
    return vs.QdrantStore(url, "col", dim, client=client or MagicMock())


def test_collection_name_slug():
    assert (
        vs.collection_name("movies", "BAAI/bge-small-en-v1.5")
        == "movies__bge-small-en-v1-5"
    )


def test_build_filter():
    assert vs.build_filter() is None
    f = vs.build_filter(genres=["Drama"], year_min=1990, year_max=2000)
    assert len(f.must) == 2
    assert f.must[0].match.any == ["Drama"]
    assert (f.must[1].range.gte, f.must[1].range.lte) == (1990, 2000)
    assert len(vs.build_filter(year_max=2000).must) == 1


@pytest.mark.parametrize(
    "url,args,kwargs",
    [
        (":memory:", (":memory:",), {}),
        ("qdrant", (), {"path": "qdrant"}),
        ("http://h:6333", (), {"url": "http://h:6333", "timeout": 30}),
    ],
)
def test_client_construction(url, args, kwargs):
    with patch.object(vs, "QdrantClient") as qc:
        vs.QdrantStore(url, "col", 3)
    qc.assert_called_once_with(*args, **kwargs)


def test_ensure_collection_creates_with_indexes():
    s = make_store()
    s.client.collection_exists.return_value = False
    s.ensure_collection()
    s.client.create_collection.assert_called_once()
    assert s.client.create_payload_index.call_count == 2
    assert s._known_to_exist


def test_ensure_collection_local_skips_indexes():
    s = make_store(url=":memory:")
    s.client.collection_exists.return_value = False
    s.ensure_collection()
    s.client.create_payload_index.assert_not_called()


def test_dim_mismatch_raises_and_match_passes():
    s = make_store(dim=3)
    s.client.collection_exists.return_value = True
    s.client.get_collection.return_value.config.params.vectors = MagicMock(size=5)
    with pytest.raises(vs.CollectionMismatchError):
        s.ensure_collection()
    s.client.get_collection.return_value.config.params.vectors = MagicMock(size=3)
    s.ensure_collection()
    s.client.create_collection.assert_not_called()


def test_require_collection():
    s = make_store()
    s.client.collection_exists.return_value = False
    with pytest.raises(vs.CollectionNotFoundError):
        s.require_collection()
    s.client.collection_exists.return_value = True
    s.client.get_collection.return_value.config.params.vectors = MagicMock(size=3)
    s.require_collection()
    s.client.collection_exists.reset_mock()
    s.require_collection()  # cached
    s.client.collection_exists.assert_not_called()


def test_existing_ids_chunks_requests():
    s = make_store()
    s.client.retrieve.side_effect = [[MagicMock(id=1)], [MagicMock(id=3)]]
    assert s.existing_ids([1, 2, 3], chunk=2) == {1, 3}
    assert s.client.retrieve.call_count == 2


def test_upsert():
    s = make_store()
    with pytest.raises(ValueError):
        s.upsert([MovieDoc(1, "a")], [])
    s.upsert([MovieDoc(1, "a", {"title": "A"})], [[0.1, 0.2, 0.3]])
    pts = s.client.upsert.call_args.kwargs["points"]
    assert pts[0].id == 1 and pts[0].payload == {"title": "A"}
    assert s.client.upsert.call_args.kwargs["wait"] is True


def test_search_maps_hits():
    s = make_store()
    s._known_to_exist = True
    point = MagicMock(id="7", score=0.9, payload={"title": "T"}, vector=[1.0, 2.0])
    s.client.query_points.return_value.points = [point]

    hit = s.search([0.1], with_vectors=True)[0]
    assert (hit.tmdb_id, hit.score, hit.payload, hit.vector) == (
        7,
        0.9,
        {"title": "T"},
        [1.0, 2.0],
    )
    assert s.search([0.1], with_vectors=False)[0].vector is None


def test_count_and_healthy():
    s = make_store()
    s.client.count.return_value.count = 42
    assert s.count() == 42
    assert s.healthy() is True
    s.client.get_collections.side_effect = RuntimeError
    assert s.healthy() is False
