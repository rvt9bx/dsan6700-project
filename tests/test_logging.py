"""Structured logging: request ids, one line per request, and nothing private in the logs."""

import json
import time

import pytest
import requests
from fastapi.testclient import TestClient
from pydantic import ValidationError

from movierec.api import main
from movierec.api.schemas import MovieRecommendation, RecommendationResponse
from movierec.config import Settings, settings
from movierec.datacollection.tmdb import describe_error
from movierec.logging_setup import json_line

client = TestClient(main.app)

SECRET_TEXT = "a-private-wish-nobody-should-read"


@pytest.fixture(autouse=True)
def no_jobs(monkeypatch):
    monkeypatch.setattr(main, "jobs", {})


@pytest.fixture
def fake_recommender(monkeypatch):
    """recommend_for_group without Qdrant or the model: one movie, every time."""

    def recommend(query_texts, top_k):
        movie = MovieRecommendation(id="546554", title="Knives Out", group_score=0.81)
        return RecommendationResponse(top_pick=movie, alternates=[])

    monkeypatch.setattr(main, "recommend_for_group", recommend)


def request_lines(records):
    """The one-per-request summary lines among the captured records."""
    return [r for r in records if r["message"] == "Request finished"]


def wait_for_job(job_id, timeout=5.0):
    """Poll the real job thread until it finishes, as the frontend does."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if main.jobs[job_id]["status"] in {"completed", "failed"}:
            return
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


# ---- request ids


def test_every_response_has_a_new_request_id():
    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]

    assert len(first) == 32
    assert first != second


def test_callers_request_id_is_reused():
    response = client.get("/health", headers={"X-Request-ID": "report-42"})

    assert response.headers["X-Request-ID"] == "report-42"


@pytest.mark.parametrize("unsafe", ["has spaces", "x" * 65, '"quoted"'])
def test_unsafe_request_id_is_replaced(unsafe):
    response = client.get("/health", headers={"X-Request-ID": unsafe})

    assert response.headers["X-Request-ID"] != unsafe


# ---- one line per request


def test_request_line_has_endpoint_status_and_duration(log_records):
    response = client.get("/recommend/nope/status")

    [line] = request_lines(log_records)
    assert line["level"].name == "WARNING"  # the caller's mistake
    assert line["extra"]["request_id"] == response.headers["X-Request-ID"]
    assert line["extra"]["method"] == "GET"
    assert line["extra"]["endpoint"] == "/recommend/{job_id}/status"
    assert line["extra"]["status"] == 404
    assert line["extra"]["job_id"] == "nope"
    assert line["extra"]["model"] == settings.embed_model
    assert line["extra"]["duration_ms"] >= 0


def test_static_and_unknown_paths_do_not_put_raw_paths_in_endpoint(log_records):
    client.get("/static/app.js")
    client.get("/no/such/page")

    assert [r["extra"]["endpoint"] for r in request_lines(log_records)] == [
        "/static",
        "unmatched",
    ]


def test_job_lines_carry_the_submitting_request_id(log_records, fake_recommender):
    response = client.post("/recommend", json={"query_texts": ["a", "b"], "top_k": 3})
    job_id = response.json()["job_id"]
    wait_for_job(job_id)

    [done] = [r for r in log_records if r["message"] == "Recommendation job completed"]
    assert done["extra"]["request_id"] == response.headers["X-Request-ID"]
    assert done["extra"]["job_id"] == job_id
    assert done["extra"]["model"] == settings.embed_model
    assert done["extra"]["num_queries"] == 2
    assert done["extra"]["num_results"] == 1
    assert done["extra"]["top_score"] == 0.81
    assert done["extra"]["empty_retrieval"] is False
    assert done["extra"]["duration_ms"] >= 0


def test_failed_job_is_logged_as_an_error_with_its_ids(log_records, monkeypatch):
    def crash(query_texts, top_k):
        raise ConnectionError("Qdrant is down")

    monkeypatch.setattr(main, "recommend_for_group", crash)
    response = client.post("/recommend", json={"query_texts": ["anything"]})
    wait_for_job(response.json()["job_id"])

    [failed] = [r for r in log_records if r["message"] == "Recommendation job failed"]
    assert failed["level"].name == "ERROR"
    assert failed["extra"]["request_id"] == response.headers["X-Request-ID"]
    assert failed["exception"] is not None


def test_unexpected_error_is_a_json_500_with_the_request_id(log_records, monkeypatch):
    def crash(q):
        raise RuntimeError("bug")

    monkeypatch.setattr(main, "search_movies", crash)

    response = client.get("/movies/search", params={"q": "heist"})

    assert response.status_code == 500
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "try again" in response.json()["detail"]
    [line] = request_lines(log_records)
    assert line["level"].name == "ERROR"


def test_invalid_request_logs_the_field_names(log_records):
    client.post("/recommend", json={"query_texts": ["a"], "top_k": 0})

    [invalid] = [r for r in log_records if r["message"] == "Invalid request"]
    assert invalid["extra"]["invalid_fields"] == ["body.top_k"]


# ---- nothing private in the logs


def test_users_text_is_never_logged(log_records, fake_recommender):
    ok = client.post("/recommend", json={"query_texts": [SECRET_TEXT]})
    wait_for_job(ok.json()["job_id"])
    client.post("/recommend", json={"query_texts": [SECRET_TEXT + "x" * 1000]})
    client.get("/movies/search", params={"q": SECRET_TEXT})

    assert log_records
    for record in log_records:
        assert SECRET_TEXT not in json_line(record)


def test_tmdb_errors_are_described_without_their_url():
    error = requests.exceptions.ConnectionError(
        "Max retries exceeded with url: /3/search/movie?api_key=SECRET123&query=Heat"
    )

    assert describe_error(error) == "ConnectionError"
    assert "SECRET123" not in describe_error(error)


# ---- JSON format


def test_each_line_is_flat_json(log_records):
    response = client.get("/health")

    [line] = request_lines(log_records)
    entry = json.loads(json_line(line))
    assert entry["level"] == "INFO"
    assert entry["message"] == "Request finished"
    assert entry["request_id"] == response.headers["X-Request-ID"]
    assert entry["endpoint"] == "/health"
    assert "ts" in entry
    assert not any(key.startswith("_") for key in entry)


# ---- settings


def test_bad_log_level_is_rejected_at_startup():
    with pytest.raises(ValidationError, match="log_level"):
        Settings(log_level="LOUD")


def test_log_level_is_case_insensitive():
    assert Settings(log_level="debug").log_level == "DEBUG"
