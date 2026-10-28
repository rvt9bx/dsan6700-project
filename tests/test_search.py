from movierec.retrieval import Hit, search

PAYLOAD = {
    "title": "Knives Out",
    "overview": "A detective untangles a wealthy family's alibis.",
    "year": 2019,
    "genres": ["Comedy", "Crime", "Mystery"],
    "poster_path": "/pThyQovXQrw2m0s9x82twj48Jq4.jpg",
}


class FakeRetriever:
    """Returns the same hit for every query, so no Qdrant or model is needed."""

    def search_many(self, query_texts, limit):
        return [[Hit(tmdb_id=546554, score=0.8, payload=PAYLOAD)] for _ in query_texts]


def test_recommendation_carries_movie_details(monkeypatch):
    monkeypatch.setattr(search, "_retriever", FakeRetriever())

    pick = search.recommend_for_group(["a whodunit", "something funny"]).top_pick

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
