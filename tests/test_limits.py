"""Rate limits, job caps, body limits, caching and the operator-only /metrics route."""

import re
import time

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from pydantic import SecretStr, ValidationError

from movierec.api import main
from movierec.api.limits import RateLimiter
from movierec.api.schemas import MovieRecommendation, RecommendationResponse
from movierec.config import Settings, settings

client = TestClient(main.app)

VALID = {"query_texts": ["a cozy mystery"]}
TOKEN = "a-long-enough-operator-token"


class FakeClock:
    """A clock the test moves by hand, so no test has to sleep."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def no_jobs(monkeypatch):
    monkeypatch.setattr(main, "jobs", {})


@pytest.fixture
def no_background_jobs(monkeypatch):
    """Accept jobs without starting their threads."""
    monkeypatch.setattr(main.threading, "Thread", lambda **kw: _NoThread())


class _NoThread:
    def start(self):
        pass


@pytest.fixture
def strict_limit(monkeypatch):
    """One recommendation per minute, with a clock the test controls."""
    clock = FakeClock()
    monkeypatch.setattr(
        main, "recommend_limiter", RateLimiter(per_minute=1, burst=1, clock=clock)
    )
    return clock


@pytest.fixture
def metrics_token(monkeypatch):
    monkeypatch.setattr(settings, "metrics_token", SecretStr(TOKEN))


# ---- the rate limiter itself


def test_burst_is_allowed_then_the_caller_must_wait():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=6, burst=2, clock=clock)

    assert limiter.acquire("a") == 0
    assert limiter.acquire("a") == 0
    assert limiter.acquire("a") == 10  # one token every 10 seconds


def test_tokens_refill_over_time():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=6, burst=1, clock=clock)
    limiter.acquire("a")

    clock.now += 4
    assert limiter.acquire("a") == 6
    clock.now += 6
    assert limiter.acquire("a") == 0


def test_each_client_has_its_own_limit():
    limiter = RateLimiter(per_minute=1, burst=1, clock=FakeClock())

    assert limiter.acquire("a") == 0
    assert limiter.acquire("b") == 0
    assert limiter.acquire("a") > 0


# ---- 429 and 503 on POST /recommend


def test_too_many_recommendations_is_429_with_retry_after(
    strict_limit, no_background_jobs
):
    assert client.post("/recommend", json=VALID).status_code == 202

    response = client.post("/recommend", json=VALID)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert "60 seconds" in response.json()["detail"]


def test_after_retry_after_the_caller_is_allowed_again(
    strict_limit, no_background_jobs
):
    client.post("/recommend", json=VALID)
    retry_after = int(client.post("/recommend", json=VALID).headers["Retry-After"])

    strict_limit.now += retry_after

    assert client.post("/recommend", json=VALID).status_code == 202


def test_invalid_requests_do_not_use_up_the_limit(strict_limit, no_background_jobs):
    for _ in range(3):
        client.post("/recommend", json={"query_texts": []})

    assert client.post("/recommend", json=VALID).status_code == 202


def test_too_many_jobs_in_flight_is_503_with_retry_after(
    monkeypatch, no_background_jobs
):
    monkeypatch.setattr(settings, "max_jobs_in_flight", 1)
    assert client.post("/recommend", json=VALID).status_code == 202

    response = client.post("/recommend", json=VALID)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(main.BUSY_RETRY_AFTER_SECONDS)


def test_finished_jobs_are_forgotten_after_their_ttl(no_background_jobs):
    an_hour_and_a_bit_ago = time.monotonic() - settings.job_ttl_seconds - 1
    main.jobs["old"] = {"status": "completed", "finished_at": an_hour_and_a_bit_ago}
    main.jobs["recent"] = {"status": "completed", "finished_at": time.monotonic()}

    client.post("/recommend", json=VALID)

    assert "old" not in main.jobs
    assert "recent" in main.jobs


# ---- what callers may send: 411, 413, 415


def test_body_over_the_limit_is_413():
    big = '{"query_texts": ["' + "x" * settings.max_body_bytes + '"]}'

    response = client.post(
        "/recommend", content=big, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413
    assert str(settings.max_body_bytes) in response.json()["detail"]


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/x-www-form-urlencoded", None]
)
@pytest.mark.parametrize("path", ["/recommend", "/events/watch"])
def test_body_that_is_not_json_is_415(path, content_type):
    headers = {"Content-Type": content_type} if content_type else {}

    response = client.post(path, content=b'{"query_texts": ["x"]}', headers=headers)

    assert response.status_code == 415
    assert "application/json" in response.json()["detail"]


def test_json_with_a_charset_is_accepted(no_background_jobs):
    response = client.post(
        "/recommend",
        content=b'{"query_texts": ["x"]}',
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 202


def test_body_without_a_length_is_411():
    def chunks():
        yield b'{"query_texts": ["x"]}'

    response = client.post(
        "/recommend", content=chunks(), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 411


def test_turned_away_bodies_are_logged_under_their_route(log_records):
    client.post("/recommend", content=b"x", headers={"Content-Type": "text/plain"})

    [line] = [r for r in log_records if r["message"] == "Request finished"]
    assert line["extra"]["endpoint"] == "/recommend"
    assert line["extra"]["status"] == 415


# ---- Cache-Control


@pytest.mark.parametrize(
    "path", ["/health", "/ready", "/recommend/nope/status", "/movies/search?q=x"]
)
def test_api_answers_are_never_stored(monkeypatch, path):
    monkeypatch.setattr(main, "ready_check", lambda: True)  # no Qdrant needed

    assert client.get(path).headers["Cache-Control"] == "no-store"


def test_completed_results_are_never_stored():
    movie = {"id": "1", "title": "Knives Out", "group_score": 0.8}
    main.jobs["job-1"] = {
        "status": "completed",
        "result": {"top_pick": movie, "alternates": []},
        "error": None,
        "finished_at": time.monotonic(),
    }

    response = client.get("/recommend/job-1/results")

    assert response.headers["Cache-Control"] == "no-store"


def test_page_links_static_files_by_content_hash_and_revalidates():
    response = client.get("/")

    assert response.headers["Cache-Control"] == "no-cache"
    links = re.findall(r'"(/static/[\w.-]+\?v=[0-9a-f]{12})"', response.text)
    assert {link.split("?")[0] for link in links} == {
        "/static/app.js",
        "/static/styles.css",
        "/static/girls-couch.webp",
    }
    for link in links:
        static = client.get(link)
        assert static.status_code == 200
        assert static.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_static_file_without_a_hash_revalidates():
    assert client.get("/static/app.js").headers["Cache-Control"] == "no-cache"


# ---- /metrics is for operators only


def test_metrics_without_a_configured_token_is_403(monkeypatch):
    monkeypatch.setattr(settings, "metrics_token", None)

    response = client.get("/metrics", headers={"Authorization": "Bearer anything"})

    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": TOKEN}],
)
def test_metrics_without_the_right_token_is_401(metrics_token, headers):
    response = client.get("/metrics", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_metrics_with_the_token_reports_requests_and_jobs(metrics_token):
    client.get("/health")

    response = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert 'movierec_http_requests_total{endpoint="/health"' in response.text
    assert "movierec_recommend_job_duration_seconds" in response.text
    assert "movierec_recommend_empty_results_total" in response.text


def test_metric_labels_hold_no_job_ids(metrics_token):
    client.get("/recommend/a-secret-job-id/status")

    response = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})

    assert "a-secret-job-id" not in response.text
    assert 'endpoint="/recommend/{job_id}/status"' in response.text


def test_a_completed_job_is_counted(monkeypatch):
    def recommend(query_texts, top_k):
        movie = MovieRecommendation(id="1", title="Knives Out", group_score=0.8)
        return RecommendationResponse(top_pick=movie, alternates=[])

    monkeypatch.setattr(main, "recommend_for_group", recommend)
    main.jobs["job-1"] = {
        "status": "pending",
        "result": None,
        "error": None,
        "finished_at": None,
    }

    def completed():
        return REGISTRY.get_sample_value(
            "movierec_recommend_jobs_total", {"outcome": "completed"}
        )

    before = completed() or 0.0
    main._run_recommendation_job("job-1", ["a"], 5)

    assert completed() == before + 1


# ---- settings


def test_short_metrics_token_is_rejected_at_startup():
    with pytest.raises(ValidationError, match="16 characters"):
        Settings(metrics_token="short")


def test_empty_metrics_token_means_unset():
    assert Settings(metrics_token="").metrics_token is None


@pytest.mark.parametrize(
    "field", ["recommend_rate_per_minute", "recommend_burst", "max_jobs_in_flight"]
)
def test_limits_must_be_positive(field):
    with pytest.raises(ValidationError, match=field):
        Settings(**{field: 0})
