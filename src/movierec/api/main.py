from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from movierec.api.schemas import RecommendationRequest
from movierec.retrieval.search import search_movies

app = FastAPI(title="Eenie Meenie Movies", version="0.1.0")

# Demo-only: replace with a persistent job store for production
jobs: dict[str, dict[str, Any]] = {}


@app.get("/", include_in_schema=False)
def home():
    # Adjust this path
    return FileResponse("movierec/frontend/index.html")


@app.post("/recommend", status_code=202)
def submit_recommendation(request: RecommendationRequest):
    job_id = str(uuid4())

    jobs[job_id] = {
        "status": "pending",
        "request": request.model_dump(),
        "result": None,
        "error": None,
    }

    # TODO: Enqueue recommendation work here
    # The worker should update jobs[job_id] to "running", then either:
    #   {"status": "completed", "result": ...}
    # or:
    #   {"status": "failed", "error": ...}

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
    # TODO: Adapt this call to search_movies' actual signature and return type
    return search_movies(q)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    # TODO: Check that Qdrant is reachable and usable.
    return {"status": "ready"}


# FastAPI serves interactive API docs at /docs by default
