"""Tests for the evaluation modules: build_eval_set.py and compare_retrieval.py.

Run with:  uv run pytest test_eval.py

Everything is stubbed with tmp files, MagicMock and monkeypatch; fixtures live in this file,
and nothing touches Qdrant, embeddings or the network.
"""

from __future__ import annotations

import json
import logging
import math
import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

import movierec.evaluation.build_eval_set as bes
import movierec.evaluation.compare_retrieval as cr

# =========================================================================== shared helpers
N_MOVIES = 30
EXCLUDED_TAGS = ["good movie", "imdb top rated", "007"]  # rejected by EXCLUDE_PATTERNS


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def hits(ids: list[int]) -> list[SimpleNamespace]:
    """Stand-in for Hit objects: the compare script only reads .tmdb_id."""
    return [SimpleNamespace(tmdb_id=i) for i in ids]


# =========================================================================== build_eval_set
@pytest.fixture
def eval_env(tmp_path, monkeypatch):
    """Tiny movies / links / tag-score files on disk, with bes.settings pointed at them.

    Movie i has tmdb id 1000 + i and MovieLens id i + 1. Tags and the movies scoring 0.81-0.95
    on them (everything else scores 0.1):
        time travel 0-14, heist 8-22, space 15-29, plus three tags the filters must reject.
    """
    movies = pd.DataFrame(
        {
            "tmdb_id": [1000 + i for i in range(N_MOVIES)],
            "title": [f"Movie {i}" for i in range(N_MOVIES)],
            "overview": [f"Overview of movie {i}" for i in range(N_MOVIES)],
        }
    )
    links = pd.DataFrame(
        {
            "movieId": range(1, N_MOVIES + 1),
            "imdbId": range(1, N_MOVIES + 1),
            "tmdbId": [1000 + i for i in range(N_MOVIES)],
        }
    )
    high = {
        "time travel": range(15),
        "heist": range(8, 23),
        "space": range(15, 30),
        **{tag: range(15) for tag in EXCLUDED_TAGS},
    }
    rows = [
        (tag, i + 1, 0.95 - 0.01 * (i - span.start) if i in span else 0.1)
        for tag, span in high.items()
        for i in range(N_MOVIES)
    ]
    tagdl = pd.DataFrame(rows, columns=["tag", "item_id", "score"])

    paths = SimpleNamespace(
        movies_path=tmp_path / "movies.csv",
        tags_path=tmp_path / "tagdl.csv",
        links_path=tmp_path / "links.csv",
        eval_path=tmp_path
        / "out"
        / "eval_queries.jsonl",  # parent dir doesn't exist yet
    )
    movies.to_csv(paths.movies_path, index=False)
    tagdl.to_csv(paths.tags_path, index=False)
    links.to_csv(paths.links_path, index=False)
    monkeypatch.setattr(bes, "settings", paths)
    return paths


MAIN_ARGS = [
    "--n-single", "10",  # more than the usable tags, so every usable tag is picked
    "--n-multi", "2",
    "--min-relevant", "3",
    "--max-relevant", "5",
    "--min-score", "0.5",
]  # fmt: skip


# ---- tag filtering ---------------------------------------------------------
@pytest.mark.parametrize(
    "tag, expected",
    [
        ("time travel", True),
        ("heist", True),
        ("dark comedy", True),
        ("IMDB Top Rated", False),  # case-insensitive
        ("good soundtrack", False),
        ("funny", False),
        ("sequel", False),
        ("007", False),
        ("2001 monolith", False),  # contains a standalone number
        ("ab", False),  # too short
    ],
)
def test_tag_allowed(tag, expected):
    import re

    patterns = [re.compile(p) for p in bes.EXCLUDE_PATTERNS]
    assert bes.tag_allowed(tag, patterns) is expected


# ---- title normalisation ---------------------------------------------------
def test_title_key_matches_movielens_and_tmdb_styles():
    assert bes.title_key("Godfather, The (1972)") == ("thegodfather", 1972)
    assert bes.title_key("The Godfather", 1972) == ("thegodfather", 1972)
    assert bes.title_key("Godfather, The (1972)") == bes.title_key(
        "The Godfather", 1972
    )


def test_title_key_strips_accents_and_punctuation():
    assert bes.title_key("Amélie (2001)") == ("amelie", 2001)
    assert bes.title_key("Se7en") == ("se7en", None)
    assert bes.title_key("Mr. & Mrs. Smith (2005)") == ("mrmrssmith", 2005)


def test_title_key_explicit_year_wins_and_empty_is_safe():
    assert bes.title_key("Film (1999)", 2000) == ("film", 2000)
    assert bes.title_key("") == ("", None)
    assert bes.title_key(None) == ("", None)  # type: ignore[arg-type]


# ---- id mapping ------------------------------------------------------------
def test_build_item_to_tmdb_keeps_only_known_ids(tmp_path):
    links = pd.DataFrame(
        {
            "movieId": [1, 2, 3, 4],
            "imdbId": [1, 2, 3, 4],
            "tmdbId": [100, 200, None, 999],
        }
    )
    links_path = tmp_path / "links.csv"
    links.to_csv(links_path, index=False)
    records = [SimpleNamespace(tmdb_id=100), SimpleNamespace(tmdb_id=200)]

    mapping = bes.build_item_to_tmdb(records, links_path)

    # movie 3 has no tmdbId, movie 4's tmdb id isn't in the collection
    assert mapping == {1: 100, 2: 200}


def test_build_item_to_tmdb_exits_when_nothing_maps(tmp_path):
    links_path = tmp_path / "links.csv"
    pd.DataFrame({"movieId": [1], "imdbId": [1], "tmdbId": [555]}).to_csv(
        links_path, index=False
    )
    with pytest.raises(SystemExit):
        bes.build_item_to_tmdb([SimpleNamespace(tmdb_id=1)], links_path)
    with pytest.raises(SystemExit):
        bes.build_item_to_tmdb([SimpleNamespace(tmdb_id=1)], None)


# ---- score matrix ----------------------------------------------------------
def test_load_score_matrix(tmp_path):
    rows = [
        ("a", 1, 0.9), ("b", 1, 0.8), ("null", 1, 0.7),
        ("a", 2, 0.5), ("b", 2, 0.4), ("null", 2, 0.3),
        ("a", 3, 0.2), ("null", 3, 0.1),  # movie 3 has no "b" score
        ("a", 99, 0.99), ("b", 99, 0.99), ("null", 99, 0.99),  # not mapped -> dropped
        ("a", 7, 0.11), ("b", 7, 0.22), ("null", 7, 0.33),  # same tmdb id as movie 1
    ]  # fmt: skip
    path = tmp_path / "tagdl.csv"
    pd.DataFrame(rows, columns=["tag", "item_id", "score"]).to_csv(path, index=False)

    # chunksize=3 forces the chunked reader to stitch several chunks together
    S, tags, tmdb_ids = bes.load_score_matrix(
        path, {1: 101, 2: 102, 3: 103, 7: 101}, chunksize=3
    )

    assert tags == ["a", "b", "null"]  # "null" survives as a real tag, not NaN
    assert list(tmdb_ids) == [101, 102, 103]
    assert S.dtype == np.float32
    expected = np.array(
        [
            [0.9, 0.8, 0.7],  # duplicate (movie 7) ignored: first occurrence wins
            [0.5, 0.4, 0.3],
            [0.2, -1.0, 0.1],  # missing pair filled with -1
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(S, expected, rtol=1e-6)


# ---- query text ------------------------------------------------------------
def test_a_picks_article_by_first_letter():
    assert bes._a("time travel") == "a time travel"
    assert bes._a("aliens") == "an aliens"
    assert bes._a("Oscar") == "an Oscar"


def test_every_template_formats_without_error():
    for template in bes.SINGLE_TEMPLATES:
        assert "alpha" in template.format(tag="alpha", a_tag=bes._a("alpha"))
    for template in bes.MULTI_TEMPLATES:
        text = template.format(t1="alpha", t2="beta", a_t1=bes._a("alpha"))
        assert "alpha" in text and "beta" in text


def test_make_query_mentions_every_tag_and_is_seeded():
    assert "heist" in bes.make_query(["heist"], random.Random(1))
    both = bes.make_query(["heist", "space"], random.Random(1))
    assert "heist" in both and "space" in both
    assert bes.make_query(["heist"], random.Random(7)) == bes.make_query(
        ["heist"], random.Random(7)
    )


# ---- generate --------------------------------------------------------------
@pytest.fixture
def score_matrix():
    """40 movies x 4 tags. alpha: movies 0-19; beta: 10-29; gamma: copy of alpha; delta: 3 movies."""
    ids = np.arange(1000, 1040)
    S = np.full((40, 4), 0.1, dtype=np.float32)
    for i in range(20):
        S[i, 0] = 0.99 - 0.01 * i  # alpha 0.99 .. 0.80, strictly decreasing
        S[i, 2] = S[i, 0]  # gamma identical -> near-synonym of alpha
    for i in range(10, 30):
        S[i, 1] = 1.0 - 0.01 * i  # beta 0.90 .. 0.71
    S[[0, 1, 2], 3] = 0.9  # delta: too few movies to be usable
    return SimpleNamespace(S=S, tags=["alpha", "beta", "gamma", "delta"], ids=ids)


def run_generate(m, **overrides):
    kwargs = {
        "allowed": [0, 1, 2, 3],
        "n_single": 10,
        "n_multi": 0,
        "min_score": 0.7,
        "min_relevant": 5,
        "max_relevant": 8,
        "rng": random.Random(0),
    }
    kwargs.update(overrides)
    return bes.generate(m.S, m.tags, m.ids, **kwargs)


def test_generate_single_tag_items(score_matrix):
    items = run_generate(score_matrix)

    by_tag = {i["tags"][0]: i for i in items}
    assert set(by_tag) == {"alpha", "beta", "gamma"}  # delta has < min_relevant movies
    assert all(i["kind"] == "single" for i in items)

    alpha = by_tag["alpha"]
    assert alpha["relevant_ids"] == [1000 + i for i in range(8)]  # capped, best first
    assert alpha["relevant_scores"] == pytest.approx(
        [0.99 - 0.01 * i for i in range(8)], abs=1e-4
    )
    assert len(alpha["relevant_ids"]) == len(alpha["relevant_scores"])
    assert by_tag["beta"]["relevant_ids"] == [1010 + i for i in range(8)]


def test_generate_respects_n_single_and_allowed(score_matrix):
    assert len(run_generate(score_matrix, n_single=2)) == 2
    only_beta = run_generate(score_matrix, allowed=[1])
    assert [i["tags"] for i in only_beta] == [["beta"]]


def test_generate_multi_tag_items(score_matrix):
    items = run_generate(score_matrix, n_single=0, n_multi=5)

    assert items, "expected at least one multi-tag query"
    assert all(i["kind"] == "multi" and len(i["tags"]) == 2 for i in items)
    pairs = {frozenset(i["tags"]) for i in items}
    # alpha+gamma are identical (overlap > 0.7) and must be skipped; delta is unusable
    assert pairs == {frozenset({"alpha", "beta"}), frozenset({"beta", "gamma"})}

    for item in items:
        # relevant = movies high on BOTH tags (10-19), ranked by the lower of the two scores
        assert all(1010 <= i <= 1019 for i in item["relevant_ids"])
        assert item["relevant_ids"] == [1010 + i for i in range(8)]
        # alpha/gamma (0.89, 0.88, ...) is the lower score here, not beta (0.90, 0.89, ...)
        assert item["relevant_scores"] == pytest.approx(
            [0.99 - 0.01 * (10 + k) for k in range(8)], abs=1e-4
        )


def test_generate_multi_skips_pairs_with_too_little_overlap(score_matrix):
    # alpha (0-19) and beta (10-29) share only 10 movies; demanding 11 rules the pair out
    items = run_generate(
        score_matrix, n_single=0, n_multi=3, min_relevant=11, max_relevant=30
    )
    assert items == []


def test_generate_is_reproducible_and_fills_queries(score_matrix):
    first = run_generate(score_matrix, n_multi=2, rng=random.Random(42))
    second = run_generate(score_matrix, n_multi=2, rng=random.Random(42))
    assert first == second
    for item in first:
        assert item["query"]
        assert all(tag in item["query"] for tag in item["tags"])
        assert len(set(item["relevant_ids"])) == len(item["relevant_ids"])
        assert all(isinstance(i, int) for i in item["relevant_ids"])


def test_generate_warns_when_it_cannot_build_enough_multi_queries(score_matrix, caplog):
    with caplog.at_level(logging.WARNING, logger="build_eval_set"):
        run_generate(score_matrix, n_single=0, n_multi=50)
    assert "multi-tag queries" in caplog.text


# ---- main ------------------------------------------------------------------
def test_build_main_writes_eval_set(eval_env):
    assert bes.main(MAIN_ARGS) == 0

    items = read_jsonl(eval_env.eval_path)  # also proves the output folder was created
    singles = [i for i in items if i["kind"] == "single"]
    multis = [i for i in items if i["kind"] == "multi"]
    assert len(multis) == 2
    # rejected tags never appear, so exactly the three content tags are used
    assert {i["tags"][0] for i in singles} == {"time travel", "heist", "space"}

    valid_ids = {1000 + i for i in range(N_MOVIES)}
    for item in items:
        assert set(item) >= {"query", "relevant_ids", "relevant_scores", "tags", "kind"}
        assert 3 <= len(item["relevant_ids"]) <= 5
        assert set(item["relevant_ids"]) <= valid_ids
        assert len(item["relevant_ids"]) == len(item["relevant_scores"])

    by_tag = {i["tags"][0]: i for i in singles}
    assert by_tag["time travel"]["relevant_ids"] == [1000, 1001, 1002, 1003, 1004]
    assert by_tag["space"]["relevant_ids"] == [1015, 1016, 1017, 1018, 1019]
    assert {frozenset(i["tags"]) for i in multis} == {
        frozenset({"time travel", "heist"}),
        frozenset({"heist", "space"}),
    }


def test_build_main_is_deterministic(eval_env):
    bes.main(MAIN_ARGS)
    first = eval_env.eval_path.read_text(encoding="utf-8")
    eval_env.eval_path.unlink()
    bes.main(MAIN_ARGS)
    assert eval_env.eval_path.read_text(encoding="utf-8") == first


def test_build_main_list_tags_prints_and_writes_nothing(eval_env, capsys):
    assert bes.main(["--list-tags", "--min-score", "0.5"]) == 0

    lines = capsys.readouterr().out.strip().splitlines()
    counts = dict(line.split("\t") for line in lines)
    assert counts == {"heist": "15", "space": "15", "time travel": "15"}
    assert not eval_env.eval_path.exists()


def test_build_main_exits_when_inputs_are_missing(eval_env):
    eval_env.links_path.unlink()
    with pytest.raises(SystemExit):
        bes.main(MAIN_ARGS)
    eval_env.tags_path.unlink()
    with pytest.raises(SystemExit):
        bes.main(MAIN_ARGS)


# =========================================================================== compare_retrieval
# ---- metrics ---------------------------------------------------------------
RELEVANT = {1, 2, 3, 4}
RANKED = [1, 9, 2, 8, 3, 7, 6, 5, 4, 0]


def test_precision_at_k():
    assert cr.precision_at_k(RANKED, RELEVANT, 5) == pytest.approx(3 / 5)
    assert cr.precision_at_k([1], RELEVANT, 10) == pytest.approx(
        0.1
    )  # divides by k, not len
    assert cr.precision_at_k([], RELEVANT, 5) == 0.0


def test_recall_at_k():
    assert cr.recall_at_k(RANKED, RELEVANT, 5) == pytest.approx(3 / 4)
    assert cr.recall_at_k(RANKED, RELEVANT, 10) == 1.0
    assert (
        cr.recall_at_k(RANKED, set(), 5) == 0.0
    )  # no relevant movies: no division error


def test_ndcg_at_k():
    dcg = 1 / math.log2(2) + 1 / math.log2(4) + 1 / math.log2(6)
    ideal = sum(1 / math.log2(r + 2) for r in range(4))
    assert cr.ndcg_at_k(RANKED, RELEVANT, 5) == pytest.approx(dcg / ideal)
    assert cr.ndcg_at_k([1, 2], {1, 2}, 5) == pytest.approx(1.0)  # best possible order
    assert cr.ndcg_at_k([9, 8], RELEVANT, 5) == 0.0
    assert cr.ndcg_at_k([], RELEVANT, 5) == 0.0
    assert cr.ndcg_at_k([1], set(), 5) == 0.0


def test_ndcg_ideal_is_capped_by_k():
    # 4 relevant but k=2: two relevant results in the top 2 is already perfect
    assert cr.ndcg_at_k([1, 2, 9], RELEVANT, 2) == pytest.approx(1.0)


def test_reciprocal_rank():
    assert cr.reciprocal_rank([1, 9], RELEVANT) == 1.0
    assert cr.reciprocal_rank([9, 8, 2], RELEVANT) == pytest.approx(1 / 3)
    assert cr.reciprocal_rank([9, 8], RELEVANT) == 0.0
    assert cr.reciprocal_rank([], RELEVANT) == 0.0


def test_query_metrics_has_every_key():
    metrics = cr.query_metrics(RANKED, RELEVANT, [5, 10])
    assert set(metrics) == {"P@5", "R@5", "nDCG@5", "P@10", "R@10", "nDCG@10", "MRR"}
    assert metrics["P@5"] == pytest.approx(0.6)
    assert metrics["MRR"] == 1.0


# ---- eval file / summaries -------------------------------------------------
def test_load_eval_set(tmp_path):
    path = tmp_path / "eval.jsonl"
    write_jsonl(
        path,
        [
            {"query": "a", "relevant_ids": [1, 2, 2], "kind": "single", "tags": ["x"]},
            {"query": "b", "relevant_ids": [3]},  # no kind
        ],
    )
    rows = cr.load_eval_set(path)
    assert rows == [
        {"query": "a", "relevant": {1, 2}, "kind": "single"},
        {"query": "b", "relevant": {3}, "kind": "unknown"},
    ]


def test_summarise_averages_only_the_selected_queries():
    per_query = [
        {"P@1": 1.0, "MRR": 1.0},
        {"P@1": 0.0, "MRR": 0.5},
        {"P@1": 0.5, "MRR": 0.0},
    ]
    assert cr.summarise(per_query, [0, 1, 2]) == pytest.approx({"P@1": 0.5, "MRR": 0.5})
    assert cr.summarise(per_query, [1]) == {"P@1": 0.0, "MRR": 0.5}


def test_write_results_creates_json_file(tmp_path):
    results = {
        "all": {"vector": {"P@2": 0.5}, "bm25": {"P@2": 0.25}},
        "single": {"vector": {"P@2": 1.0}, "bm25": {"P@2": 0.0}},
    }
    groups = {"all": [0, 1], "single": [0]}
    out_dir = tmp_path / "does" / "not" / "exist"

    path = cr.write_results(results, groups, [2], Path("eval.jsonl"), out_dir)

    assert path.parent == out_dir and path.name.startswith("eval_results_")
    data = json.loads(path.read_text())
    assert data["eval_file"] == "eval.jsonl"
    assert data["cutoffs_k"] == [2]
    assert data["groups"]["all"]["num_queries"] == 2
    assert data["groups"]["single"]["methods"]["bm25"] == {"P@2": 0.0}


# ---- parser ----------------------------------------------------------------
def test_build_parser_defaults_and_overrides(monkeypatch):
    monkeypatch.setattr(
        cr, "settings", SimpleNamespace(eval_path=Path("from_settings.jsonl"))
    )
    args = cr.build_parser().parse_args([])
    assert args.eval_file == Path("from_settings.jsonl")
    assert args.k == [10]

    args = cr.build_parser().parse_args(["mine.jsonl", "--k", "5", "10", "20"])
    assert args.eval_file == Path("mine.jsonl")
    assert args.k == [5, 10, 20]


# ---- main ------------------------------------------------------------------
@pytest.fixture
def cr_env(tmp_path, monkeypatch):
    """Stub the retrievers so main() runs with known rankings (no Qdrant, no embeddings).

    Two queries: q1 (single) relevant {1, 2}; q2 (multi) relevant {3, 4}.
        vector returns q1 -> [1, 2, 9], q2 -> [9, 8, 7]
        bm25   returns q1 -> [9, 1, 5], q2 -> [3, 8, 7]
    Each ranking is cut to the `limit` the script asks for.
    """
    eval_file = tmp_path / "eval.jsonl"
    write_jsonl(
        eval_file,
        [
            {"query": "q1", "relevant_ids": [1, 2], "kind": "single"},
            {"query": "q2", "relevant_ids": [3, 4], "kind": "multi"},
        ],
    )
    vector_rank = [[1, 2, 9], [9, 8, 7]]
    bm25_rank = {"q1": [9, 1, 5], "q2": [3, 8, 7]}

    vec = MagicMock()
    vec.embed_queries.side_effect = lambda qs: [[0.0]] * len(qs)
    vec.search_vectors.side_effect = lambda vectors, limit: [
        hits(vector_rank[n][:limit]) for n in range(len(vectors))
    ]
    vec.store.existing_ids.return_value = {1, 2, 3, 4}

    bm25 = MagicMock()
    bm25.search_many.side_effect = lambda qs, limit: [
        hits(bm25_rank[q][:limit]) for q in qs
    ]

    retriever_cls = MagicMock()
    retriever_cls.from_settings.return_value = vec
    bm25_cls = MagicMock()
    bm25_cls.from_store.return_value = bm25
    monkeypatch.setattr(cr, "Retriever", retriever_cls)
    monkeypatch.setattr(cr, "BM25Retriever", bm25_cls)
    monkeypatch.setattr(
        cr, "settings", SimpleNamespace(eval_path=eval_file, project_root=tmp_path)
    )
    return SimpleNamespace(
        eval_file=eval_file, vec=vec, bm25=bm25, bm25_cls=bm25_cls, root=tmp_path
    )


def load_results(env) -> dict:
    files = list((env.root / "data" / "eval" / "results").glob("eval_results_*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text())


def test_compare_main_computes_and_saves_metrics(cr_env, capsys):
    assert cr.main([str(cr_env.eval_file), "--k", "2"]) == 0

    out = capsys.readouterr().out
    assert "2 queries" in out and "Results written to" in out
    assert "warning" not in out

    data = load_results(cr_env)
    assert data["cutoffs_k"] == [2]
    assert set(data["groups"]) == {"all", "single", "multi"}
    assert data["groups"]["all"]["num_queries"] == 2

    methods = {g: data["groups"][g]["methods"] for g in data["groups"]}
    # vector: q1 perfect, q2 finds nothing
    assert methods["all"]["vector"]["P@2"] == pytest.approx(0.5)
    assert methods["all"]["vector"]["MRR"] == pytest.approx(0.5)
    assert methods["single"]["vector"]["R@2"] == pytest.approx(1.0)
    assert methods["multi"]["vector"]["P@2"] == 0.0
    # bm25: q1 hits at rank 2, q2 hits at rank 1 (rankings are cut to the top 2)
    assert methods["all"]["bm25"]["MRR"] == pytest.approx(0.75)
    assert methods["all"]["bm25"]["P@2"] == pytest.approx(0.5)
    one_hit_at_rank_2 = (1 / math.log2(3)) / (1 + 1 / math.log2(3))
    assert methods["single"]["bm25"]["nDCG@2"] == pytest.approx(one_hit_at_rank_2)


def test_compare_main_searches_down_to_the_largest_k(cr_env):
    cr.main([str(cr_env.eval_file), "--k", "3", "1"])

    assert cr_env.vec.search_vectors.call_args.kwargs["limit"] == 3
    assert cr_env.bm25.search_many.call_args.args[0] == ["q1", "q2"]
    assert cr_env.bm25.search_many.call_args.kwargs["limit"] == 3
    cr_env.bm25_cls.from_store.assert_called_once_with(
        cr_env.vec.store
    )  # same corpus as vector

    metrics = load_results(cr_env)["groups"]["all"]["methods"]["vector"]
    assert set(metrics) == {"P@1", "R@1", "nDCG@1", "P@3", "R@3", "nDCG@3", "MRR"}


def test_compare_main_warns_about_relevant_ids_missing_from_qdrant(cr_env, capsys):
    cr_env.vec.store.existing_ids.return_value = {1, 2, 3}  # id 4 was never ingested
    cr.main([str(cr_env.eval_file), "--k", "2"])
    assert "only 3/4 relevant ids" in capsys.readouterr().out


def test_compare_main_single_kind_has_only_the_all_group(cr_env):
    write_jsonl(
        cr_env.eval_file,
        [
            {"query": "q1", "relevant_ids": [1, 2], "kind": "single"},
            {"query": "q2", "relevant_ids": [3, 4], "kind": "single"},
        ],
    )
    cr_env.vec.search_vectors.side_effect = lambda vectors, limit: (
        [hits([1, 2])] * len(vectors)
    )
    cr.main([str(cr_env.eval_file), "--k", "2"])
    assert set(load_results(cr_env)["groups"]) == {"all"}


# =========================================================================== config guard
def test_settings_defines_the_eval_paths_the_scripts_use():
    from movierec.config import Settings

    for name in ("movies_path", "tags_path", "links_path", "eval_path"):
        assert name in Settings.model_fields, f"Settings is missing {name}"
