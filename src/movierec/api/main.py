import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from movierec.api.schemas import RecommendationRequest
from movierec.retrieval.search import (
    health_check,
    ready_check,
    recommend_for_group,
    search_movies,
)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

app = FastAPI(title="Eenie Meenie Movies", version="0.1.0")
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

# Demo-only: replace with a persistent job store for production
jobs: dict[str, dict[str, Any]] = {}


def _run_recommendation_job(job_id: str, query_texts: list[str], top_k: int) -> None:
    """Background worker: run recommendation and update job status."""
    jobs[job_id]["status"] = "running"
    try:
        result = recommend_for_group(query_texts, top_k)
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result.model_dump()
    except Exception as e:  # noqa: BLE001
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(UI_DIR / "index.html")


@app.post("/recommend", status_code=202)
def submit_recommendation(request: RecommendationRequest):
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


@app.get("/recommend/{job_id}/status")
def recommendation_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"job_id": job_id, "status": job["status"], "error": job["error"]}


@app.get("/recommend/{job_id}/results")
def recommendation_results(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] in {"pending", "running"}:
        raise HTTPException(status_code=202, detail="Job is still processing")

    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=job["error"] or "Job failed")

    return job["result"]


@app.get("/movies/search")
def movie_search(q: str):
    # Placeholder for future searchbar UI
    return search_movies(q)


@app.get("/health")
def health():
    return {"status": "ok" if health_check() else "degraded"}


@app.get("/ready")
def ready():
    return {"status": "ready" if ready_check() else "not ready"}


# FastAPI serves interactive API docs at /docs by default
