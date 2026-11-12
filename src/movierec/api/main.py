import logging
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from movierec.api.events import record_event
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
from movierec.retrieval.search import (
    ready_check,
    recommend_for_group,
    search_movies,
)

logger = logging.getLogger(__name__)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

app = FastAPI(
    title="Eenie Meenie Movies",
    version="0.1.0",
    description="Solo or group movie recommendations from natural-language descriptions. "
    "Recommendations run as background jobs: submit one with `POST /recommend`, poll its "
    "status, then fetch the results. The README has a curl command for every endpoint.",
)
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

# Demo-only: replace with a persistent job store for production
jobs: dict[str, dict[str, Any]] = {}

JOB_NOT_FOUND = {
    "model": ErrorMessage,
    "description": "No job with this id (jobs are lost when the server restarts)",
}


def _run_recommendation_job(job_id: str, query_texts: list[str], top_k: int) -> None:
    """Background worker: run recommendation and update job status."""
    jobs[job_id]["status"] = "running"
    try:
        result = recommend_for_group(query_texts, top_k)
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result.model_dump()
    except Exception:
        # The details go to the server log; callers only see that it failed
        logger.exception("Recommendation job %s failed", job_id)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = (
            "The recommendation failed on the server. Please try again."
        )


def _get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No job with id {job_id!r}. Jobs are kept in memory, so they are lost "
            "when the server restarts; submit a new one with POST /recommend.",
        )
    return job


@app.get("/", summary="The web app", response_class=FileResponse, tags=["UI"])
def home():
    """The page people use to get a recommendation. Its scripts and styles are under /static."""
    return FileResponse(UI_DIR / "index.html")


@app.post(
    "/recommend",
    status_code=202,
    response_model=JobAccepted,
    summary="Start a recommendation",
    tags=["Recommendations"],
)
def submit_recommendation(request: RecommendationRequest):
    """Starts a recommendation for one person or a group, and returns its job id at once.

    Poll `GET /recommend/{job_id}/status` until the status is `completed` or `failed`.
    Returns 422 if the body is invalid: no descriptions, a blank one, more than six people,
    or `top_k` outside 1 to 20.
    """
    job_id = str(uuid4())

    jobs[job_id] = {
        "status": "pending",
        "request": request.model_dump(),
        "result": None,
        "error": None,
    }

    thread = threading.Thread(
        target=_run_recommendation_job,
        args=(job_id, request.query_texts, request.top_k),
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
    """Called when someone taps "We're watching ...". Appends the click to the usage log."""
    # job_id is not checked against jobs: they are lost on restart, the click is still real
    record_event("watch_click", job_id=event.job_id, movie_id=event.movie_id)


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
