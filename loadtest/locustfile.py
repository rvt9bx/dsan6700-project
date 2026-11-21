"""Locust load test: simulated groups getting a movie recommendation, as the web page does.

Each simulated user is one group on movie night: it opens the page, submits everyone's
descriptions, waits out Retry-After when the server is busy, polls the job every second
until it is done (giving up after a minute), and reads the results. Then it waits a
while and does it again.

Install and run (see "Load testing" in the README):

    uv sync --group loadtest
    uv run locust -f loadtest/locustfile.py --host https://<instance-hostname>

Every request id starts with "locust-", so this traffic can be told apart in the logs:

    jq 'select(.request_id | startswith("locust-"))' app.jsonl

It never taps "We're watching ...", so the usage numbers don't get fake clicks.
"""

from __future__ import annotations

import random
import time
from uuid import uuid4

from locust import HttpUser, between, task

# time.sleep is safe here: Locust patches it so one waiting user doesn't block the others

# Match the web page (src/movierec/ui/app.js), so the load looks like real use
TOP_K = 8
POLL_SECONDS = 1.0
POLL_TIMEOUT_SECONDS = 60
BUSY_TRIES = 4
MAX_RETRY_AFTER_SECONDS = 60

DESCRIPTIONS = [
    "a cozy mystery with a twist I won't see coming",
    "something funny, nothing too long",
    "dark and tense, keep me on the edge of my seat",
    "feel-good, like a warm blanket",
    "big loud action, pure fun",
    "smart sci-fi we'll argue about after",
    "a heist with a clever crew",
    "an animated movie the whole family can watch",
    "a slow-burn romance set somewhere beautiful",
    "a true story about an underdog",
    "a scary movie, but not too gory",
    "a musical with great songs",
]
# Most groups are two to four people
GROUP_SIZES = [1, 2, 3, 4, 5, 6]
GROUP_SIZE_WEIGHTS = [2, 4, 4, 3, 1, 1]


class JobFailed(Exception):
    """A recommendation did not come back: refused, failed, or too slow."""


class MovieNightUser(HttpUser):
    """One group asking for a recommendation every 10 to 30 seconds."""

    wait_time = between(10, 30)

    def on_start(self) -> None:
        """Open the page, as a person does before typing anything."""
        self.client.get("/", headers=self._headers())

    @task
    def movie_night(self) -> None:
        """Submit, wait, poll and fetch results; record the whole wait as one entry.

        Locust lists each request separately. The "movie night" entry under FLOW is what a
        person actually waits for, from tapping the button to seeing the results.
        """
        size = random.choices(GROUP_SIZES, GROUP_SIZE_WEIGHTS)[0]
        body = {"query_texts": random.sample(DESCRIPTIONS, size), "top_k": TOP_K}
        started = time.perf_counter()
        error: Exception | None = None
        try:
            job_id = self._submit(body)
            self._wait_for(job_id)
            self._fetch_results(job_id)
        except JobFailed as exc:
            error = exc
        self.environment.events.request.fire(
            request_type="FLOW",
            name="movie night (submit to results)",
            response_time=(time.perf_counter() - started) * 1000,
            response_length=0,
            exception=error,
            context={},
        )

    def _submit(self, body: dict) -> str:
        """POST /recommend, waiting out Retry-After on 429 or 503 like the page does."""
        for attempt in range(1, BUSY_TRIES + 1):
            with self.client.post(
                "/recommend", json=body, headers=self._headers(), catch_response=True
            ) as response:
                if response.status_code == 202:
                    return response.json()["job_id"]
                if response.status_code in (429, 503):
                    wait = self._retry_after(response.headers.get("Retry-After"))
                    response.failure(
                        f"{response.status_code}, told to wait {wait} s "
                        f"(try {attempt} of {BUSY_TRIES})"
                    )
                    if attempt < BUSY_TRIES:
                        time.sleep(wait)
                    continue
                response.failure(f"unexpected {response.status_code}")
                raise JobFailed(f"POST /recommend answered {response.status_code}")
        raise JobFailed(f"still busy after {BUSY_TRIES} tries")

    def _wait_for(self, job_id: str) -> None:
        """Poll the job's status every second until it finishes, for up to a minute."""
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with self.client.get(
                f"/recommend/{job_id}/status",
                name="/recommend/{job_id}/status",
                headers=self._headers(),
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"unexpected {response.status_code}")
                    raise JobFailed(f"status answered {response.status_code}")
                status = response.json()["status"]
            if status == "completed":
                return
            if status == "failed":
                raise JobFailed("the job failed on the server")
            time.sleep(POLL_SECONDS)
        raise JobFailed(f"not done after {POLL_TIMEOUT_SECONDS} s")

    def _fetch_results(self, job_id: str) -> None:
        """GET the results and check there is a top pick."""
        with self.client.get(
            f"/recommend/{job_id}/results",
            name="/recommend/{job_id}/results",
            headers=self._headers(),
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"unexpected {response.status_code}")
                raise JobFailed(f"results answered {response.status_code}")
            if not response.json()["top_pick"]["id"]:
                response.failure("no movies found")
                raise JobFailed("the search found no movies")

    @staticmethod
    def _headers() -> dict[str, str]:
        """A fresh request id per request, marked so the logs can tell it is a load test."""
        return {"X-Request-ID": f"locust-{uuid4().hex}"}

    @staticmethod
    def _retry_after(header: str | None) -> int:
        """Seconds to wait from a Retry-After header: 5 if missing, between 1 and 60."""
        try:
            seconds = int(header) if header else 5
        except ValueError:
            seconds = 5
        return min(max(seconds, 1), MAX_RETRY_AFTER_SECONDS)
