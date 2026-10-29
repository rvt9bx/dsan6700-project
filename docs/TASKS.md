# From architecture to tasks

How the architecture became work. Each line is a GitHub issue; each issue gets a branch and a pull request that a
teammate reviews. The first milestone is a **walking skeleton**: the thinnest version that works end to end.

Status as of 2026-10-29. Numbers in brackets are GitHub issues (`#`) and pull requests (`PR #`).

## Milestone 1: walking skeleton (everything connected, nothing good yet) — done
1. Project setup: `pyproject.toml`, uv, ruff, pytest, CI on pushes to `main` and on pull requests. **Done**
2. Settings: a `Settings` class read from the environment (`src/movierec/config.py`, `.env.example`). **Done**
3. Data in: filter IMDB titles and ratings, enrich them with TMDB overviews, genres and posters, and write
   `tmdb_movies.parquet`; ingest validates and cleans each row before embedding. **Done** [#6, PR #19]
4. A model interface and the simplest model that fits it: a `Retriever` that embeds text with fastembed
   (`BAAI/bge-small-en-v1.5`, CPU only) and searches Qdrant by cosine similarity, one collection per embedding model.
   **Done** [#7, #17, PR #18, PR #19]
5. Core output step, with a test that proves it works: retrieve for each person, merge, average their scores into one
   group ranking, and return a top pick and alternates with poster, year and genres (`tests/test_search.py`).
   **Done** [PR #19, PR #22]
6. The API: `POST /recommend`, `GET /recommend/{job_id}/status`, `GET /recommend/{job_id}/results`, `/health`,
   `/ready`, with schemas; `/movies/search` is a placeholder for later. **Done** [#4, PR #15, PR #19]
7. The user-facing page: a page served by FastAPI where each person takes a turn on one device, then everyone sees
   the group pick. **Done** [#5, #14, PR #13, PR #20, PR #24]
8. Docker and Compose; deploy on Jetstream2; only the app's port open (8080; Qdrant's 6333 stays internal).
   **Done** [#2, #8, PR #16, PR #18]
9. Solution and technical architecture diagrams (`docs/ARCHITECTURE.md`). **In progress** [#1, PR #25]

## Milestone 2: measure
10. Build the evaluation set from the MovieLens tag genome: turn tag-weight vectors into natural-language queries,
    with the top-ranked genome movies as ground truth.
11. Run the BM25 baseline and the embedding retriever on it; record precision@K, recall@K and nDCG.
12. Group evaluation: synthetic groups from MovieLens ratings (similar, dissimilar, random) to score each member and
    the group.
13. Error analysis: which queries and which groups fail, and why.

## Milestone 3: first users (Homework 3)
14. Write the user brief; open the testing window; answer every issue.

## Milestone 4: iterate
15. Better group aggregation: score every pooled movie for every person, and compare social-choice methods beyond the
    mean. [#21]
16. UI improvements from user feedback, starting with details for the alternate picks. [#23]
17. Try better embedding models behind the same `Retriever` interface; pick one by the numbers and by user feedback.
18. Ship it by changing a setting (`EMBED_MODEL` creates its own Qdrant collection, so switching back is a rollback),
    and measure again.
