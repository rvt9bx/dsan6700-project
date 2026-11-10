import json

import pytest
from fastapi.testclient import TestClient

from movierec.api.events import EVENTS_FILENAME
from movierec.api.main import app
from movierec.config import settings

client = TestClient(app)


@pytest.fixture
def events_file(monkeypatch, tmp_path):
    log_dir = tmp_path / "logs"  # does not exist yet: the first write creates it
    monkeypatch.setattr(settings, "log_dir", log_dir)
    return log_dir / EVENTS_FILENAME


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_watch_click_is_logged(events_file):
    response = client.post(
        "/events/watch", json={"job_id": "job-1", "movie_id": "546554"}
    )

    assert response.status_code == 204
    [event] = read_events(events_file)
    assert event["event"] == "watch_click"
    assert event["job_id"] == "job-1"
    assert event["movie_id"] == "546554"
    assert "ts" in event


def test_every_click_gets_its_own_line(events_file):
    for movie_id in ("1", "2", "2"):
        client.post("/events/watch", json={"job_id": "job-1", "movie_id": movie_id})

    assert [e["movie_id"] for e in read_events(events_file)] == ["1", "2", "2"]


def test_click_for_a_job_lost_in_a_restart_is_still_logged(events_file):
    # Jobs live in memory, so a results page can outlive the job it came from
    response = client.post(
        "/events/watch", json={"job_id": "unknown", "movie_id": "546554"}
    )

    assert response.status_code == 204
    assert len(read_events(events_file)) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"job_id": "job-1"},
        {"movie_id": "546554"},
        {"job_id": "x" * 65, "movie_id": "546554"},
        {"job_id": "job-1", "movie_id": "x" * 33},
    ],
)
def test_malformed_click_is_rejected_and_not_logged(events_file, body):
    response = client.post("/events/watch", json=body)

    assert response.status_code == 422
    assert not events_file.exists()
