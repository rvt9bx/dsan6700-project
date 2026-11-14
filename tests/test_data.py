"""Tests for movierec.retrieval.data."""

import pandas as pd
import pytest

from movierec.retrieval.data import (
    TEXT_VERSION,
    MovieRecord,
    clean_row,
    clean_text,
    iter_movies,
    movie_to_payload,
    movie_to_text,
    parse_float,
    parse_genres,
    parse_int,
    parse_year,
)


# ---------------------------------------------------------------- parsing helpers
@pytest.mark.parametrize(
    "value,expected",
    [
        ("Hello\nworld", "Hello world"),
        ("Hello\t\tworld", "Hello world"),
        ("  Hello   world  ", "Hello world"),
        (None, ""),
        (float("nan"), ""),
        (45.6, ""),  # any float is treated as NaN-like
        (0.0, ""),
        (123, "123"),
        (True, "True"),
    ],
)
def test_clean_text(value, expected):
    assert clean_text(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("42", 42),
        ("  42  ", 42),
        ("0", 0),
        ("-5", -5),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_parse_int(value, expected):
    assert parse_int(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("3.14", 3.14),
        ("  2.5  ", 2.5),
        ("0", 0.0),
        ("-1.5", -1.5),
        (2.5, 2.5),
        ("inf", None),
        ("-inf", None),
        ("nan", None),
        ("", None),
        ("   ", None),
        (None, None),
        (0.0, 0.0),
        (0, 0.0),
    ],
)
def test_parse_float(value, expected):
    assert parse_float(value) == expected


@pytest.mark.parametrize(
    "release_date,year_value,expected",
    [
        ("2019-05-15", None, 2019),
        ("2020-01-01", "2019", 2020),  # release_date wins
        (None, "2019", 2019),
        (None, None, None),
        ("not-a-date", "2020", 2020),
        ("", "2020", 2020),
        ("2020-13-45", "2019", 2020),  # only first 4 chars are read
    ],
)
def test_parse_year(release_date, year_value, expected):
    assert parse_year(release_date, year_value) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Action,Adventure", ["Action", "Adventure"]),
        ("['Action', 'Adventure']", ["Action", "Adventure"]),
        ('["Action", "Adventure"]', ["Action", "Adventure"]),
        ("[{'id': 18, 'name': 'Drama'}]", ["Drama"]),
        ("Action , Adventure ", ["Action", "Adventure"]),
        (" 'Action' , \"Adventure\" ", ["Action", "Adventure"]),
        ("Action", ["Action"]),
        ("", []),
        ("[]", []),
        (None, []),
        (float("nan"), []),
        (["Action", "Adventure"], ["Action", "Adventure"]),  # already a list
    ],
)
def test_parse_genres(raw, expected):
    assert parse_genres(raw) == expected


# ---------------------------------------------------------------- row cleaning
FULL_ROW = {
    "tmdb_id": "546554",
    "title": "Knives Out",
    "overview": "A detective untangles a wealthy family's alibis.",
    "release_date": "2019-11-07",
    "year": "2019",
    "genres": "['Comedy', 'Crime', 'Mystery']",
    "poster_path": "/pThyQovXQrw2m0s9x82twj48Jq4.jpg",
    "popularity": "123.45",
    "runtime": "130",
}


def test_clean_row_populates_all_fields():
    assert clean_row(pd.Series(FULL_ROW)) == MovieRecord(
        tmdb_id=546554,
        title="Knives Out",
        overview="A detective untangles a wealthy family's alibis.",
        year=2019,
        genres=["Comedy", "Crime", "Mystery"],
        poster_path="/pThyQovXQrw2m0s9x82twj48Jq4.jpg",
        popularity=123.45,
        runtime=130.0,
    )


@pytest.mark.parametrize("missing", ["tmdb_id", "title", "overview"])
def test_clean_row_requires_id_title_overview(missing):
    row = {"tmdb_id": "123", "title": "Movie", "overview": "Overview"}
    del row[missing]
    assert clean_row(pd.Series(row)) is None


def test_clean_row_optional_fields_default():
    rec = clean_row(
        pd.Series({"tmdb_id": "123", "title": "Movie", "overview": "Overview"})
    )
    assert (rec.year, rec.genres, rec.poster_path, rec.popularity, rec.runtime) == (
        None,
        [],
        None,
        None,
        None,
    )


# ---------------------------------------------------------------- iter_movies
@pytest.mark.parametrize("ext", ["parquet", "csv"])
def test_iter_movies_reads_file_and_skips_invalid_rows(tmp_path, ext):
    df = pd.DataFrame(
        [
            {"tmdb_id": 1, "title": "Valid", "overview": "Good", "year": 2019},
            {"tmdb_id": 2, "title": "No Overview", "overview": None},
            {"tmdb_id": 3, "title": "Valid 2", "overview": "Also good", "year": 2020},
        ]
    )
    path = tmp_path / f"movies.{ext}"
    df.to_parquet(path) if ext == "parquet" else df.to_csv(path, index=False)

    records = list(iter_movies(path))
    assert [(r.tmdb_id, r.title, r.year) for r in records] == [
        (1, "Valid", 2019),
        (3, "Valid 2", 2020),
    ]


def test_iter_movies_missing_required_columns(tmp_path):
    path = tmp_path / "movies.csv"
    pd.DataFrame([{"tmdb_id": 1, "title": "No overview column"}]).to_csv(
        path, index=False
    )
    with pytest.raises(ValueError, match="overview"):
        list(iter_movies(path))


# ---------------------------------------------------------------- text & payload
def test_movie_to_text_exact_format():
    rec = MovieRecord(
        tmdb_id=1,
        title="Knives Out",
        overview="A detective untangles a wealthy family's alibis.",
        year=2019,
        genres=["Comedy", "Crime", "Mystery"],
        popularity=12.5,
    )
    assert movie_to_text(rec) == (
        "Knives Out (2019). Genres: Comedy, Crime, Mystery. 12.5. "
        "A detective untangles a wealthy family's alibis."
    )


def test_movie_to_text_omits_missing_optionals():
    rec = MovieRecord(tmdb_id=1, title="Old Movie", overview="An old movie.")
    assert movie_to_text(rec) == "Old Movie. An old movie."


def test_movie_to_text_does_not_double_punctuation():
    rec = MovieRecord(tmdb_id=1, title="Who?", overview="Overview.")
    assert movie_to_text(rec) == "Who? Overview."


def test_movie_to_text_keeps_overview_whitespace_as_is():
    rec = MovieRecord(tmdb_id=1, title="Movie", overview="Line 1\n\nLine 2\t\tLine 3")
    assert movie_to_text(rec).endswith("Line 1\n\nLine 2\t\tLine 3")


def test_movie_to_payload_full():
    rec = MovieRecord(
        tmdb_id=546554,
        title="Knives Out",
        overview="A detective story",
        year=2019,
        genres=["Comedy", "Crime", "Mystery"],
        poster_path="/poster.jpg",
        popularity=123.45,
        runtime=130.0,
    )
    assert movie_to_payload(rec) == {
        "title": "Knives Out",
        "overview": "A detective story",
        "year": 2019,
        "genres": ["Comedy", "Crime", "Mystery"],
        "poster_path": "/poster.jpg",
        "popularity": 123.45,
        "runtime": 130.0,
        "text_version": TEXT_VERSION,
    }


def test_movie_to_payload_keeps_none_values():
    payload = movie_to_payload(
        MovieRecord(tmdb_id=1, title="Minimal", overview="Just a movie")
    )
    assert payload["year"] is None and payload["genres"] == []
    assert payload["poster_path"] is None and payload["popularity"] is None
    assert payload["runtime"] is None and payload["text_version"] == TEXT_VERSION
