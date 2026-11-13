"""The FastAPI app: recommendation jobs, status endpoints, usage events and the web UI."""

import contextvars
import functools
import hashlib
import re
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from movierec.api import metrics
from movierec.api.auth import require_operator
from movierec.api.limits import RateLimiter
from movierec.api.middleware import log_requests
from movierec.api.policies import apply_request_policies
from movierec.api.schemas import (
    MAX_QUERY_CHARS,
    ErrorMessage,
    HealthStatus,
    JobAccepted,
    JobStatus,
    MovieRecommendation,
    ReadyStatus,
    RecommendationRequest,
    RecommendationResponse,
    WatchEvent,
)
from movierec.config import settings
from movierec.logging_setup import configure_logging
from movierec.retrieval.search import (
    ready_check,
    recommend_for_group,
    search_movies,
)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Set up logging when the server starts (after uvicorn has set up its own)."""
    configure_logging()
    logger.bind(version=APP_VERSION, model=settings.embed_model).info("App starting")
    yield
    logger.info("App stopping")


app = FastAPI(
    lifespan=lifespan,
    title="Eenie Meenie Movies",
    version=APP_VERSION,
    description="Solo or group movie recommendations from natural-language descriptions. "
    "Recommendations run as background jobs: submit one with `POST /recommend`, poll its "
    "status, then fetch the results. The README has a curl command for every endpoint.",
)
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")
# The last middleware added runs first: log_requests wraps everything, so requests
# that the policies turn away (413, 415) are logged with a request id too
app.middleware("http")(apply_request_policies)
app.middleware("http")(log_requests)

# Demo-only: replace with a persistent job store for production. Finished jobs are
# forgotten after JOB_TTL_SECONDS, and at most MAX_JOBS_IN_FLIGHT run at once
jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
BUSY_RETRY_AFTER_SECONDS = 5

recommend_limiter = RateLimiter(
    per_minute=settings.recommend_rate_per_minute, burst=settings.recommend_burst
)

JOB_NOT_FOUND = {
    "model": ErrorMessage,
    "description": "No job with this id: finished jobs are kept for an hour, and all jobs "
    "are lost when the server restarts",
}


def _run_recommendation_job(job_id: str, query_texts: list[str], top_k: int) -> None:
    """Background worker: run the recommendation, update the job, and log how it went.

    Logs counts, scores and timings only, never the descriptions themselves.
    """
    with logger.contextualize(job_id=job_id, model=settings.embed_model):
        jobs[job_id]["status"] = "running"
        metrics.JOBS_IN_FLIGHT.inc()
        started = time.perf_counter()
        try:
            result = recommend_for_group(query_texts, top_k)
        except Exception:
            # The details go to the server log; callers only see that it failed
            with logger.contextualize(duration_ms=_ms_since(started)):
                logger.exception("Recommendation job failed")
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = (
                "The recommendation failed on the server. Please try again."
            )
            _finish_job(job_id, "failed", started)
            return

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result.model_dump()
        _finish_job(job_id, "completed", started)
        empty = result.top_pick.id == ""
        metrics.QUERIES_PER_JOB.observe(len(query_texts))
        if empty:
            metrics.EMPTY_RETRIEVALS.inc()
        else:
            metrics.TOP_SCORE.observe(result.top_pick.group_score)
        logger.bind(
            duration_ms=_ms_since(started),
            num_queries=len(query_texts),
            top_k=top_k,
            num_results=0 if empty else 1 + len(result.alternates),
            top_score=None if empty else round(result.top_pick.group_score, 4),
            empty_retrieval=empty,
        ).info("Recommendation job completed")


def _finish_job(job_id: str, outcome: str, started: float) -> None:
    """Record a finished job in the metrics, and start its time-to-live."""
    jobs[job_id]["finished_at"] = time.monotonic()
    metrics.JOBS.labels(outcome=outcome).inc()
    metrics.JOB_SECONDS.observe(time.perf_counter() - started)
    metrics.JOBS_IN_FLIGHT.dec()


def _forget_expired_jobs(now: float) -> None:
    """Drop jobs that finished more than JOB_TTL_SECONDS ago. Call with _jobs_lock held."""
    expired = [
        job_id
        for job_id, job in jobs.items()
        if job["finished_at"] is not None
        and now - job["finished_at"] > settings.job_ttl_seconds
    ]
    for job_id in expired:
        del jobs[job_id]


def _jobs_in_flight() -> int:
    """How many jobs are pending or running. Call with _jobs_lock held."""
    return sum(job["status"] in {"pending", "running"} for job in jobs.values())


def _client_of(request: Request) -> str:
    """The caller's address, which rate limits are kept per.

    Behind Caddy this is the real client only if uvicorn trusts the proxy's
    X-Forwarded-For header (FORWARDED_ALLOW_IPS); otherwise every user shares one limit.
    """
    return request.client.host if request.client else "unknown"


def _ms_since(started: float) -> float:
    """Milliseconds since a time.perf_counter() reading, to one decimal place."""
    return round((time.perf_counter() - started) * 1000, 1)


def _get_job(job_id: str) -> dict[str, Any]:
    """The job with this id, or a 404 that says jobs are lost on restart."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No job with id {job_id!r}. Finished jobs are kept for an hour, and "
            "all jobs are lost when the server restarts; submit a new one with "
            "POST /recommend.",
        )
    return job


@app.exception_handler(RequestValidationError)
async def log_validation_error(
    request: Request, exc: RequestValidationError
) -> Response:
    """Log which fields were invalid (never their values), then answer FastAPI's usual 422."""
    fields = [".".join(str(part) for part in error["loc"]) for error in exc.errors()]
    logger.bind(invalid_fields=fields).warning("Invalid request")
    return await request_validation_exception_handler(request, exc)


_STATIC_URL = re.compile(r'"/static/([\w.-]+)"')


@functools.cache
def _index_html() -> str:
    """index.html with a content hash on each /static URL, e.g. /static/app.js?v=3f2a91c0d4e5.

    The hash changes only when the file does, so browsers can keep the files for a year
    (see policies.cache_control_for) and still fetch the new version after a deploy.
    """
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")

    def versioned(match: re.Match[str]) -> str:
        name = match.group(1)
        digest = hashlib.sha256((UI_DIR / name).read_bytes()).hexdigest()[:12]
        return f'"/static/{name}?v={digest}"'

    return _STATIC_URL.sub(versioned, html)


@app.get("/", summary="The web app", response_class=HTMLResponse, tags=["UI"])
def home():
    """The page people use to get a recommendation. Its scripts and styles are under /static."""
    return HTMLResponse(_index_html())


@app.post(
    "/recommend",
    status_code=202,
    response_model=JobAccepted,
    summary="Start a recommendation",
    tags=["Recommendations"],
    responses={
        413: {"model": ErrorMessage, "description": "The body is over MAX_BODY_BYTES"},
        415: {"model": ErrorMessage, "description": "The body is not JSON"},
        429: {
            "model": ErrorMessage,
            "description": "Too many recommendations from this client; wait Retry-After "
            "seconds",
        },
        503: {
            "model": ErrorMessage,
            "description": "The server is busy with other jobs; wait Retry-After seconds",
        },
    },
)
def submit_recommendation(body: RecommendationRequest, request: Request):
    """Starts a recommendation for one person or a group, and returns its job id at once.

    Poll `GET /recommend/{job_id}/status` until the status is `completed` or `failed`.
    Returns 422 if the body is invalid: no descriptions, a blank one, more than six people,
    or `top_k` outside 1 to 20. Each client may start RECOMMEND_BURST jobs at once and
    RECOMMEND_RATE_PER_MINUTE a minute after that; past that it gets a 429 with a
    Retry-After header.
    """
    wait = recommend_limiter.acquire(_client_of(request))
    if wait:
        logger.bind(retry_after_s=wait).warning("Rate limited")
        raise HTTPException(
            status_code=429,
            detail=f"Too many recommendations in a short time. Try again in {wait} "
            "seconds.",
            headers={"Retry-After": str(wait)},
        )

    job_id = str(uuid4())
    with _jobs_lock:
        _forget_expired_jobs(time.monotonic())
        if _jobs_in_flight() >= settings.max_jobs_in_flight:
            logger.warning("Too many jobs in flight")
            raise HTTPException(
                status_code=503,
                detail="The server is busy with other recommendations. Try again in "
                f"{BUSY_RETRY_AFTER_SECONDS} seconds.",
                headers={"Retry-After": str(BUSY_RETRY_AFTER_SECONDS)},
            )
        jobs[job_id] = {
            "status": "pending",
            "result": None,
            "error": None,
            "finished_at": None,
        }
    logger.bind(
        job_id=job_id, num_queries=len(body.query_texts), top_k=body.top_k
    ).info("Recommendation job accepted")

    # A new thread starts with empty context variables, so run the job inside a copy of
    # this request's context: its log lines then carry this request's request_id
    context = contextvars.copy_context()
    thread = threading.Thread(
        target=context.run,
        args=(_run_recommendation_job, job_id, body.query_texts, body.top_k),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id, "status": "pending"}


@app.get(
    "/recommend/{job_id}/status",
    response_model=JobStatus,
    summary="Check a recommendation's status",
    tags=["Recommendations"],
    responses={404: JOB_NOT_FOUND},
)
def recommendation_status(job_id: str):
    """The job's status: `pending`, `running`, `completed` or `failed`."""
    job = _get_job(job_id)
    return {"job_id": job_id, "status": job["status"], "error": job["error"]}


@app.get(
    "/recommend/{job_id}/results",
    response_model=RecommendationResponse,
    summary="Get a recommendation's results",
    tags=["Recommendations"],
    responses={
        404: JOB_NOT_FOUND,
        409: {"model": ErrorMessage, "description": "The job has not finished yet"},
        500: {"model": ErrorMessage, "description": "The job failed on the server"},
    },
)
def recommendation_results(job_id: str):
    """The top pick and alternates, once the job's status is `completed`."""
    job = _get_job(job_id)

    if job["status"] in {"pending", "running"}:
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id!r} is still {job['status']}. Poll "
            f"GET /recommend/{job_id}/status until it is completed, then ask again.",
        )

    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=job["error"])

    return job["result"]


@app.post(
    "/events/watch",
    status_code=204,
    summary="Record that a group chose a movie",
    tags=["Usage events"],
)
def log_watch(event: WatchEvent) -> None:
    """Called when someone taps "We're watching ...". Writes the click to the app's log."""
    # job_id is not checked against jobs: they are lost on restart, the click is still real
    logger.bind(event="watch_click", job_id=event.job_id, movie_id=event.movie_id).info(
        "Watch click"
    )


@app.get(
    "/movies/search",
    response_model=list[MovieRecommendation],
    summary="Search movies (placeholder)",
    tags=["Movies"],
)
def movie_search(
    q: str = Query(
        ..., min_length=1, max_length=MAX_QUERY_CHARS, description="What to search for"
    ),
):
    """Placeholder for a future search bar: returns fixed sample data for now."""
    return search_movies(q)


@app.get(
    "/health",
    response_model=HealthStatus,
    summary="Liveness check",
    tags=["Status"],
)
def health():
    """The app process is up and answering. Checks no dependencies; see /ready for those."""
    return {"status": "ok"}


@app.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics (operators only)",
    tags=["Status"],
    dependencies=[Depends(require_operator)],
    responses={
        401: {"model": ErrorMessage, "description": "Missing or wrong bearer token"},
        403: {"model": ErrorMessage, "description": "METRICS_TOKEN is not set"},
    },
)
def prometheus_metrics() -> Response:
    """Request counts, failures and timings per route, and how recommendations are going.

    Requires `Authorization: Bearer <METRICS_TOKEN>`. In Prometheus's text format.
    """
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get(
    "/ready",
    response_model=ReadyStatus,
    response_model_exclude_none=True,
    summary="Readiness check",
    tags=["Status"],
    responses={503: {"model": ReadyStatus, "description": "A dependency is not ready"}},
)
def ready():
    """Qdrant is reachable and the movie collection has movies in it."""
    try:
        is_ready = ready_check()
    except Exception:
        logger.exception("Readiness check failed")
        is_ready = False
    if not is_ready:
        logger.warning("Not ready: Qdrant is unreachable or the collection is empty")
        return JSONResponse(
            status_code=503,
            content={
                "status": "not ready",
                "detail": "Qdrant is unreachable or the movie collection is empty. "
                "Check that Qdrant is running and that ingest has been run.",
            },
        )
    return {"status": "ready"}


# FastAPI serves interactive API docs at /docs by default
