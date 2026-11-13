"""The "We're watching ..." click is written to the app's log as a watch_click event."""

import pytest
from fastapi.testclient import TestClient

from movierec.api.main import app

client = TestClient(app)


def watch_clicks(records):
    """The extra fields of each watch_click event among the captured records."""
    return [r["extra"] for r in records if r["extra"].get("event") == "watch_click"]


def test_watch_click_is_logged(log_records):
    response = client.post(
        "/events/watch", json={"job_id": "job-1", "movie_id": "546554"}
    )

    assert response.status_code == 204
    [event] = watch_clicks(log_records)
    assert event["job_id"] == "job-1"
    assert event["movie_id"] == "546554"
    assert event["request_id"] == response.headers["X-Request-ID"]


def test_every_click_gets_its_own_line(log_records):
    for movie_id in ("1", "2", "2"):
        client.post("/events/watch", json={"job_id": "job-1", "movie_id": movie_id})

    assert [e["movie_id"] for e in watch_clicks(log_records)] == ["1", "2", "2"]


def test_click_for_a_job_lost_in_a_restart_is_still_logged(log_records):
    # Jobs live in memory, so a results page can outlive the job it came from
    response = client.post(
        "/events/watch", json={"job_id": "unknown", "movie_id": "546554"}
    )

    assert response.status_code == 204
    assert len(watch_clicks(log_records)) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"job_id": "job-1"},
        {"movie_id": "546554"},
        {"job_id": "x" * 65, "movie_id": "546554"},
        {"job_id": "job-1", "movie_id": "x" * 33},
    ],
)
def test_malformed_click_is_rejected_and_not_logged(log_records, body):
    response = client.post("/events/watch", json=body)

    assert response.status_code == 422
    assert watch_clicks(log_records) == []
