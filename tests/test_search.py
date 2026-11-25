from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from movierec.api.schemas import PickFilters
from movierec.retrieval import Hit, search
from movierec.retrieval.retriever import QueryFilter

PAYLOAD = {
    "title": "Knives Out",
    "overview": "A detective untangles a wealthy family's alibis.",
    "year": 2019,
    "genres": ["Comedy", "Crime", "Mystery"],
    "poster_path": "/pThyQovXQrw2m0s9x82twj48Jq4.jpg",
}


@pytest.fixture
def mock_retriever(monkeypatch):
    r = MagicMock()
    monkeypatch.setattr(search, "_retriever", r)
    return r


def _knives_out(vector=None):
    return Hit(tmdb_id=546554, score=0.8, payload=PAYLOAD, vector=vector)


def test_recommendation_carries_movie_details(mock_retriever):
    mock_retriever.embed_queries.return_value = [[0.0] * 384, [0.0] * 384]
    mock_retriever.search_vectors.return_value = [[_knives_out([0.0] * 384)]] * 2

    pick = search.recommend_for_group(["a whodunit", "something funny"]).top_pick

    assert pick.id == "546554"
    assert pick.year == 2019
    assert pick.genres == ["Comedy", "Crime", "Mystery"]
    assert pick.poster_path == "/pThyQovXQrw2m0s9x82twj48Jq4.jpg"


def test_solo_recommendation_carries_movie_details(mock_retriever):
    mock_retriever.search.return_value = [_knives_out()]

    pick = search.recommend_for_group(["something funny"]).top_pick

    assert pick.id == "546554"
    assert pick.year == 2019
    assert pick.genres == ["Comedy", "Crime", "Mystery"]
    assert pick.poster_path == "/pThyQovXQrw2m0s9x82twj48Jq4.jpg"


def test_missing_payload_fields_default_to_empty():
    (rec,) = search._hits_to_recommendations(
        [Hit(tmdb_id=1, score=0.5, payload={"title": "Old Movie"})]
    )

    assert rec.year is None
    assert rec.genres == []
    assert rec.poster_path is None


@pytest.mark.parametrize(
    "name,scores,expected",
    [
        ("mean", [0.2, 0.4], 0.3),
        ("least_misery", [0.2, 0.4], 0.2),
        ("most_pleasure", [0.2, 0.4], 0.4),
        ("nash", [0.25, 1.0], 0.5),
        ("nash", [0.0, 1.0], 0.0),
        ("nash", [-0.5, 1.0], 0.0),  # negatives clamped
        ("fairness", [0.4, 0.4], 0.4),
        ("approval", [0.6, 0.4], 0.5 + 0.5 * 0.1 / 2),
    ],
)
def test_aggregators(name, scores, expected):
    assert search.AGGREGATION_STRATEGIES[name](scores) == pytest.approx(expected)


@pytest.mark.parametrize("fn", list(search.AGGREGATION_STRATEGIES.values()))
def test_aggregators_empty(fn):
    assert fn([]) == 0.0


def test_fairness_penalizes_disagreement():
    assert search.aggregate_fairness([0.0, 1.0]) < search.aggregate_fairness([0.5, 0.5])


def test_cosine_matrix_handles_zero_vectors():
    q = np.array([[1.0, 0.0], [0.0, 0.0]])
    m = np.array([[2.0, 0.0], [0.0, 3.0]])
    assert search._cosine_similarity_matrix(q, m).tolist() == [[1.0, 0.0], [0.0, 0.0]]


def test_get_retriever_is_singleton(monkeypatch):
    monkeypatch.setattr(search, "_retriever", None)
    with patch.object(search.Retriever, "from_settings") as fs:
        assert search._get_retriever() is search._get_retriever()
    fs.assert_called_once()
    fs.return_value.warmup.assert_called_once()


def _hit(i, vec=None, score=0.9):
    return Hit(i, score, {"title": f"M{i}"}, vec)


def test_no_queries_and_unknown_strategy(mock_retriever):
    assert search.recommend_for_group([]).top_pick.title == "No queries provided"
    with pytest.raises(ValueError, match="Unknown aggregation"):
        search.recommend_for_group(["a"], agg_fn="bogus")


def test_solo_applies_aggregator_and_limit(mock_retriever):
    mock_retriever.search.return_value = [_hit(1, score=0.8), _hit(2, score=0.5)]
    res = search.recommend_for_group(["a"], top_k=2, agg_fn=lambda s: s[0] * 2)
    mock_retriever.search.assert_called_once_with(
        "a", limit=2, genres=None, year_min=None, year_max=None
    )
    assert res.top_pick.group_score == pytest.approx(1.6)
    assert [a.id for a in res.alternates] == ["2"]


def test_solo_no_hits(mock_retriever):
    mock_retriever.search.return_value = []
    assert search.recommend_for_group(["a"]).top_pick.title == "No matches found"


def test_group_pools_dedupes_and_ranks(mock_retriever):
    mock_retriever.embed_queries.return_value = [[1.0, 0.0], [0.0, 1.0]]
    mock_retriever.search_vectors.return_value = [
        [_hit(1, [1.0, 0.0]), _hit(2, [1.0, 1.0])],
        [_hit(2, [1.0, 1.0]), _hit(3, [0.0, 1.0])],  # movie 2 repeated
    ]
    res = search.recommend_for_group(["a", "b"], top_k=3, agg_fn="least_misery")

    kwargs = mock_retriever.search_vectors.call_args.kwargs
    assert kwargs["with_vectors"] is True and kwargs["limit"] == 10  # max(top_k*3, 10)
    assert res.top_pick.id == "2"  # only movie both participants like (cos ~ 0.707)
    assert res.top_pick.group_score == pytest.approx(0.7071, abs=1e-3)
    assert len(res.top_pick.individual_scores) == 2
    assert {a.id for a in res.alternates} == {"1", "3"}


def test_group_without_vectors_means_no_matches(mock_retriever):
    mock_retriever.embed_queries.return_value = [[1.0], [1.0]]
    mock_retriever.search_vectors.return_value = [[_hit(1, None)], []]
    assert search.recommend_for_group(["a", "b"]).top_pick.title == "No matches found"


def test_ready_check(mock_retriever):
    mock_retriever.ready.return_value = True
    assert search.ready_check() is True


# ---- per-person filters: each narrows only that person's own retrieval


def test_no_filters_means_an_empty_filter_per_query():
    assert search._to_query_filters(None, 2) == [QueryFilter(), QueryFilter()]


def test_pick_filters_become_query_filters():
    filters = [PickFilters(genres=["Drama"], year_max=2000)]

    assert search._to_query_filters(filters, 1) == [QueryFilter(("Drama",), None, 2000)]


def test_solo_filters_go_to_the_search(mock_retriever):
    mock_retriever.search.return_value = [_hit(1)]
    filters = [PickFilters(genres=["Mystery", "Comedy"], year_min=1990, year_max=2015)]

    search.recommend_for_group(["a"], filters=filters)

    mock_retriever.search.assert_called_once_with(
        "a", limit=5, genres=("Comedy", "Mystery"), year_min=1990, year_max=2015
    )


def test_solo_no_hits_with_filters_says_so(mock_retriever):
    mock_retriever.search.return_value = []

    res = search.recommend_for_group(["a"], filters=[PickFilters(genres=["Western"])])

    assert res.top_pick.title == "Nothing matches those filters"


def test_group_gives_each_person_their_own_filter(mock_retriever):
    mock_retriever.embed_queries.return_value = [[1.0, 0.0], [0.0, 1.0]]
    mock_retriever.search_vectors.return_value = [
        [_hit(1, [1.0, 0.0])],
        [_hit(2, [0.0, 1.0])],
    ]
    filters = [PickFilters(genres=["Mystery"], year_min=1990), PickFilters()]

    search.recommend_for_group(["a", "b"], filters=filters)

    sent = mock_retriever.search_vectors.call_args.kwargs["filters"]
    assert sent == [QueryFilter(("Mystery",), 1990, None), QueryFilter()]


def test_group_without_filters_sends_empty_filters(mock_retriever):
    mock_retriever.embed_queries.return_value = [[1.0, 0.0], [0.0, 1.0]]
    mock_retriever.search_vectors.return_value = [[_hit(1, [1.0, 0.0])], []]

    search.recommend_for_group(["a", "b"])

    sent = mock_retriever.search_vectors.call_args.kwargs["filters"]
    assert sent == [QueryFilter(), QueryFilter()]


def test_group_no_hits_with_filters_says_so(mock_retriever):
    mock_retriever.embed_queries.return_value = [[1.0], [1.0]]
    mock_retriever.search_vectors.return_value = [[], []]
    filters = [PickFilters(year_max=1950), PickFilters()]

    res = search.recommend_for_group(["a", "b"], filters=filters)

    assert res.top_pick.title == "Nothing matches those filters"


def test_one_persons_filter_does_not_drop_movies_found_for_another(mock_retriever):
    # Movie 1 was found for Alice (Mystery). Bob filtered to Comedy, but once movies
    # are pooled they are scored on query similarity alone, so movie 1 still competes.
    mock_retriever.embed_queries.return_value = [[1.0, 0.0], [1.0, 0.0]]
    mock_retriever.search_vectors.return_value = [
        [_hit(1, [1.0, 0.0])],
        [_hit(2, [0.0, 1.0])],
    ]
    filters = [PickFilters(genres=["Mystery"]), PickFilters(genres=["Comedy"])]

    res = search.recommend_for_group(["a", "b"], agg_fn="mean", filters=filters)

    assert res.top_pick.id == "1"
    assert [a.id for a in res.alternates] == ["2"]
