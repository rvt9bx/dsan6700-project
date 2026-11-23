"""Tests for the ingest CLI (everything heavy mocked).

Adjust the import if ingest.py lives elsewhere.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from movierec.retrieval import ingest


@pytest.fixture
def env():
    records = [SimpleNamespace(tmdb_id=i) for i in range(5)]
    retriever = MagicMock()
    captured = {}

    def fake_index(docs, skip_existing):
        captured["docs"] = list(docs)
        captured["skip"] = skip_existing
        return len(captured["docs"])

    retriever.index.side_effect = fake_index
    settings = SimpleNamespace(movies_path="movies.parquet")
    with (
        patch.object(ingest, "_load_settings", return_value=settings),
        patch.object(ingest, "iter_movies", return_value=iter(records)) as im,
        patch.object(ingest, "movie_to_text", side_effect=lambda r: f"text{r.tmdb_id}"),
        patch.object(
            ingest, "movie_to_payload", side_effect=lambda r: {"id": r.tmdb_id}
        ),
        patch.object(ingest.Retriever, "from_settings", return_value=retriever),
    ):
        yield SimpleNamespace(retriever=retriever, captured=captured, iter_movies=im)


def test_parser_defaults_and_flags():
    a = ingest.build_parser().parse_args([])
    assert a.parquet is None and a.limit is None and a.reindex is False
    a = ingest.build_parser().parse_args(
        ["--limit", "3", "--reindex", "--parquet", "x.csv"]
    )
    assert (a.limit, a.reindex, str(a.parquet)) == (3, True, "x.csv")


def test_main_default_run(env):
    assert ingest.main([]) == 0
    env.iter_movies.assert_called_once()
    assert str(env.iter_movies.call_args.args[0]) == "movies.parquet"
    env.retriever.warmup.assert_called_once()
    env.retriever.store.ensure_collection.assert_called_once()
    assert env.captured["skip"] is True
    assert [d.tmdb_id for d in env.captured["docs"]] == [0, 1, 2, 3, 4]
    assert env.captured["docs"][0].text == "text0"
    assert env.captured["docs"][0].payload == {"id": 0}


def test_main_limit_and_reindex(env):
    ingest.main(["--limit", "2", "--reindex"])
    assert len(env.captured["docs"]) == 2
    assert env.captured["skip"] is False


def test_main_parquet_override(env):
    ingest.main(["--parquet", "other.parquet"])
    assert str(env.iter_movies.call_args.args[0]) == "other.parquet"


def test_load_settings_import_error():
    with (
        patch.dict("sys.modules", {"movierec.config": None}),
        pytest.raises(SystemExit),
    ):
        ingest._load_settings()
