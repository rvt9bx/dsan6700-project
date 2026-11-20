import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from movierec.api import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def no_jobs(monkeypatch):
    monkeypatch.setattr(main, "jobs", {})


def add_job(status, result=None, error=None):
    main.jobs["job-1"] = {
        "status": status,
        "result": result,
        "error": error,
        "finished_at": None,
    }


# ---- /health and /ready


def test_health_is_ok_without_touching_qdrant_or_the_model(monkeypatch):
    def fail():
        raise AssertionError("/health must not check dependencies")

    monkeypatch.setattr(main, "ready_check", fail)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_dependencies_are_ready(monkeypatch):
    monkeypatch.setattr(main, "ready_check", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_not_ready_is_503_with_a_reason(monkeypatch):
    monkeypatch.setattr(main, "ready_check", lambda: False)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not ready"
    assert "ingest" in response.json()["detail"]


def test_readiness_check_that_crashes_is_503_not_500(monkeypatch):
    def crash():
        raise ConnectionError("Qdrant is down")

    monkeypatch.setattr(main, "ready_check", crash)

    assert client.get("/ready").status_code == 503


# ---- job status and results


@pytest.mark.parametrize("path", ["/recommend/nope/status", "/recommend/nope/results"])
def test_unknown_job_is_404_naming_the_job(path):
    response = client.get(path)

    assert response.status_code == 404
    assert "'nope'" in response.json()["detail"]


@pytest.mark.parametrize("status", ["pending", "running"])
def test_results_before_the_job_finishes_is_409(status):
    add_job(status)

    response = client.get("/recommend/job-1/results")

    assert response.status_code == 409
    assert status in response.json()["detail"]


def test_results_of_a_completed_job_are_200():
    movie = {"id": "1", "title": "Knives Out", "group_score": 0.8}
    add_job("completed", result={"top_pick": movie, "alternates": []})

    response = client.get("/recommend/job-1/results")

    assert response.status_code == 200
    assert response.json()["top_pick"]["id"] == "1"


def test_failed_job_is_500_without_leaking_the_exception(monkeypatch):
    def crash(query_texts, top_k):
        raise ConnectionError("secret-internal-host:6333 refused")

    monkeypatch.setattr(main, "recommend_for_group", crash)
    add_job("pending")
    main._run_recommendation_job("job-1", ["anything"], 5)

    status = client.get("/recommend/job-1/status").json()
    results = client.get("/recommend/job-1/results")

    assert status["status"] == "failed"
    assert results.status_code == 500
    for message in (status["error"], results.json()["detail"]):
        assert "secret-internal-host" not in message
        assert "try again" in message


# ---- input validation: the caller's mistake is a 4xx that says what, never a 5xx


@pytest.fixture
def no_background_jobs(monkeypatch):
    started = []
    monkeypatch.setattr(
        main.threading, "Thread", lambda **kw: started.append(kw) or _NoThread()
    )
    return started


class _NoThread:
    def start(self):
        pass


def test_valid_request_is_accepted_with_a_job_id(no_background_jobs):
    response = client.post("/recommend", json={"query_texts": ["a cozy mystery"]})

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["job_id"] in main.jobs


@pytest.mark.parametrize(
    ("body", "problem_field"),
    [
        ({}, "query_texts"),
        ({"query_texts": []}, "query_texts"),
        ({"query_texts": ["   "]}, "query_texts"),
        ({"query_texts": ["x" * 1001]}, "query_texts"),
        ({"query_texts": ["a"] * 7}, "query_texts"),
        ({"query_texts": ["a"], "top_k": 0}, "top_k"),
        ({"query_texts": ["a"], "top_k": 21}, "top_k"),
        ({"query_texts": "not a list"}, "query_texts"),
    ],
)
def test_bad_recommend_request_is_422_naming_the_field(
    no_background_jobs, body, problem_field
):
    response = client.post("/recommend", json=body)

    assert response.status_code == 422
    [error, *_] = response.json()["detail"]
    assert problem_field in error["loc"]
    assert error["msg"]
    assert no_background_jobs == []


@pytest.mark.parametrize("query", ["", "x" * 1001])
def test_bad_search_query_is_422(query):
    assert client.get("/movies/search", params={"q": query}).status_code == 422


# ---- documentation: every endpoint in /docs and in the README


def documented_routes():
    paths = client.get("/openapi.json").json()["paths"]
    return [
        (m.upper(), path, op) for path, ops in paths.items() for m, op in ops.items()
    ]


def test_docs_page_is_served():
    assert client.get("/docs").status_code == 200


def test_every_endpoint_has_a_summary_and_description_in_docs():
    for method, path, op in documented_routes():
        assert op.get("summary"), f"{method} {path} has no summary"
        assert op.get("description"), f"{method} {path} has no description"


def test_every_endpoint_has_a_curl_command_in_the_readme():
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    curl_lines = [line for line in readme.splitlines() if "curl " in line]
    for method, path, _ in documented_routes():
        url = re.sub(r"\{job_id\}", "$JOB_ID", path)
        matches = [line for line in curl_lines if f"8080{url}" in line]
        if method == "POST":
            matches = [line for line in matches if "-X POST" in line]
        assert matches, f"README has no curl command for {method} {path}"
