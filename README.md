### Authors: 
Nkemdibe Okweye, Noelle Martell, Erin Brzusek, and Eleanor Byrd

# movierec

A package for solo or group semantic movie recommendations.

## Running with Docker

The app runs as three containers, defined in `compose.yml`:

- **app**: FastAPI and the UI on port 8080, the only published port
- **qdrant**: the vector database, reachable only by the other containers
- **ingest**: a one-off job that loads the movies into Qdrant

Start the app and Qdrant with

```bash
docker compose up -d --build
```

Qdrant starts empty. To load the movies (once per machine), put the movie Parquet at `data/clean/tmdb_movies.parquet`
and run

```bash
docker compose run --rm ingest
```

The vectors are kept in the `qdrant-storage` volume, so this does not need rerunning after restarts or rebuilds. The
Parquet is not in git; see `src/movierec/datacollection/README.md` for how it was built.

Configuration is read from the environment. Copy `.env.example` to `.env` to override defaults; `compose.yml` sets
`QDRANT_URL`, `EMBED_CACHE_DIR` and `MOVIES_PATH` for the containers.

## API

Interactive docs, with every endpoint's request and response schemas, are at `http://localhost:8080/docs` while the
app is running. On Jetstream2, replace `localhost` with the instance's hostname in the commands below.

Recommendations run as background jobs: start one, poll its status until it is `completed`, then get the results.
These three commands run in order; the first saves the job id in `JOB_ID` for the next two (it needs `python3`):

```bash
JOB_ID=$(curl -s -X POST http://localhost:8080/recommend -H 'Content-Type: application/json' -d '{"query_texts": ["a cozy mystery with a twist", "something funny, nothing too long"], "top_k": 5}' | python3 -c 'import json, sys; print(json.load(sys.stdin)["job_id"])') && echo $JOB_ID
curl -s http://localhost:8080/recommend/$JOB_ID/status
curl -s http://localhost:8080/recommend/$JOB_ID/results
```

The other endpoints:

```bash
curl -s http://localhost:8080/health
curl -s http://localhost:8080/ready
curl -s -X POST http://localhost:8080/events/watch -H 'Content-Type: application/json' -d '{"job_id": "test", "movie_id": "546554"}' -w '%{http_code}\n'
curl -s 'http://localhost:8080/movies/search?q=heist'
curl -s http://localhost:8080/ -o /dev/null -w '%{http_code}\n'
```

`/metrics` is for operators only. Set `METRICS_TOKEN` on the server (16+ characters), then send it as a bearer token:

```bash
curl -s -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8080/metrics
```

Add `-i` to any command to see the status code and headers. What each status code means:

| Code | Meaning                                                         | Returned by                                    |
|------|-----------------------------------------------------------------|------------------------------------------------|
| 200  | OK                                                              | all `GET` endpoints                            |
| 202  | Job accepted; poll its status                                   | `POST /recommend`                              |
| 204  | Click recorded; no body                                         | `POST /events/watch`                           |
| 401  | Missing or wrong bearer token                                   | `/metrics`                                     |
| 403  | `METRICS_TOKEN` is not set on the server, so nobody may call it | `/metrics`                                     |
| 404  | No job with that id: finished jobs are kept for an hour, and all jobs are lost when the server restarts | `/recommend/{job_id}/status`, `/results` |
| 409  | The job has not finished; poll `/status` and ask again          | `/recommend/{job_id}/results`                  |
| 411  | A body was sent without a `Content-Length`                      | every `POST`                                   |
| 413  | The body is over `MAX_BODY_BYTES` (32 KB)                       | every `POST`                                   |
| 415  | The body is not `Content-Type: application/json`                | every `POST`                                   |
| 422  | The request was invalid; `detail` names the field and the rule  | `POST /recommend`, `/events/watch`, `/movies/search` |
| 429  | Too many recommendations from you; wait `Retry-After` seconds   | `POST /recommend`                              |
| 500  | The job failed on the server; the details are in the app's log  | `/recommend/{job_id}/results`, any unexpected error |
| 503  | `/ready`: Qdrant is unreachable or the movies are not loaded. `POST /recommend`: too many jobs running; wait `Retry-After` seconds | `/ready`, `POST /recommend` |

`POST /recommend` takes 1 to 6 descriptions, each 1 to 1000 characters and not blank, and a `top_k` from 1 to 20.
Each client may start 5 recommendations at once (`RECOMMEND_BURST`), then 10 a minute (`RECOMMEND_RATE_PER_MINUTE`);
past that it gets a 429 with a `Retry-After` header saying how many seconds to wait. At most 8 jobs run at once
(`MAX_JOBS_IN_FLIGHT`). Every error has a JSON body, `{"detail": "..."}`, that says what went wrong.

Caching: API answers are sent with `Cache-Control: no-store`, since they can belong to one group. The page links its
files as `/static/app.js?v=<content hash>`, and those are cached for a year (`immutable`); a deploy that changes a file
changes its hash, so browsers fetch the new one.

## Logs

The app logs with [loguru](https://github.com/Delgan/loguru), one JSON object per line, to two places:

- **stdout**, which Docker keeps until the container is recreated: `docker compose logs app`
- **`app.jsonl`** in `LOG_DIR` (`logs/` when run locally, the `logs` volume in Docker), which survives redeploys. It
  rotates at 50 MB and keeps the last 5 files.

Every response has an `X-Request-ID` header, and every line written while handling that request carries the same
`request_id`, including the lines from the background job it starts. If someone reports a problem, ask for that id.
A caller can also send its own `X-Request-ID` (up to 64 letters, digits, `.`, `_` or `-`), and the app uses that one
instead.

Each request ends with one summary line:

```json
{"ts": "2026-11-13T17:35:11.052530-05:00", "level": "WARNING", "message": "Request finished", "logger": "movierec.api.middleware", "function": "log_requests", "line": 88, "request_id": "5f6ce2a5878f4ff299b50eacb2ad3f09", "method": "POST", "endpoint": "/recommend", "status": 422, "duration_ms": 1.0, "model": "BAAI/bge-small-en-v1.5"}
```

| Field                                  | On                       | Meaning                                                      |
|----------------------------------------|--------------------------|--------------------------------------------------------------|
| `request_id`                           | every line in a request  | Matches the `X-Request-ID` response header                   |
| `endpoint`, `method`, `status`         | `Request finished`       | The route template, e.g. `/recommend/{job_id}/status`        |
| `duration_ms`                          | `Request finished`, jobs | How long the request or job took                             |
| `job_id`                               | job lines, job requests  | Ties together a job's submit, status polls and results       |
| `model`                                | `/recommend*`, job lines | The embedding model (`EMBED_MODEL`)                          |
| `num_queries`, `num_results`, `top_score`, `empty_retrieval` | `Recommendation job completed` | Counts and scores for the job |
| `event: "watch_click"`, `movie_id`     | `Watch click`            | Someone tapped "We're watching ..."                          |
| `invalid_fields`                       | `Invalid request`        | Which fields a 422 was about (never their values)            |

`level` is `ERROR` when the service failed (5xx), `WARNING` when the caller sent something wrong (4xx), and `INFO`
otherwise. The app never logs what people typed, a recommendation's contents, or a secret; the tests check this.
uvicorn's own access log is turned off, because it would print query strings.

Searching the logs (needs [`jq`](https://jqlang.org/) on the host):

```bash
# everything from one request
docker compose exec app cat /logs/app.jsonl | jq 'select(.request_id == "5f6ce2a5878f4ff299b50eacb2ad3f09")'
# a whole job: its submit, its status polls and the job itself
docker compose exec app cat /logs/app.jsonl | jq 'select(.job_id == "<job id>")'
# errors only
docker compose logs app --no-log-prefix | jq -c 'select(.level == "ERROR")'
# how many times people tapped "We're watching ..."
docker compose exec app cat /logs/app.jsonl | jq -c 'select(.event == "watch_click")' | wc -l
```

`LOG_LEVEL` (default `INFO`) sets the lowest level logged. `LOG_JSON=false` prints readable text to stdout instead,
which is easier to read during development; `app.jsonl` is JSON either way.

## Deploying on Jetstream2

On the instance (an `m3.small` is enough):

```bash
git clone https://github.com/rvt9bx/dsan6700-project.git && cd dsan6700-project
docker compose up -d --build
```

From your laptop, copy the Parquet to the instance, then run ingest there:

```bash
scp tmdb_movies.parquet exouser@<instance>:~/dsan6700-project/data/clean/
```

```bash
docker compose run -d --name ingest-run ingest
docker logs -f ingest-run
```

Ingest takes 15 minutes or more; it is done when the log says `Finished ingestion`. To update after changes are merged
to `main`:

```bash
git pull && docker compose up -d --build
```

Only port 8080 is published. The containers restart on their own after a reboot or unshelve, but shelving releases the
public IP, so use the instance's hostname rather than its IP.

## Contributing

Clone and set up the repository with

```bash
git clone https://github.com/rvt9bx/dsan6700-project.git && cd dsan6700-project
uv sync
```

Install pre-commit hooks with

```bash
uv run pre-commit install
```

Run tests using

```
uv run pytest -v tests
```
