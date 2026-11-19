# movierec

A package for solo or group semantic movie recommendations.

## Running with Docker

The app runs as four containers, defined in `compose.yml`:

- **app**: FastAPI and the UI on port 8080
- **qdrant**: the vector database, reachable only by the other containers
- **ingest**: a one-off job that loads the movies into Qdrant
- **caddy**: on the instance only, serves the app over HTTPS on ports 80 and 443 (see
  [Deploying on Jetstream2](#deploying-on-jetstream2))

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
app is running. On Jetstream2, replace `http://localhost:8080` with `https://team01-app.cis240466.projects.jetstream-cloud.org`
in the commands below.

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

Add `-i` to any command to see the status code and headers. What each status code means:

| Code | Meaning                                                         | Returned by                                    |
|------|-----------------------------------------------------------------|------------------------------------------------|
| 200  | OK                                                              | all `GET` endpoints                            |
| 202  | Job accepted; poll its status                                   | `POST /recommend`                              |
| 204  | Click recorded; no body                                         | `POST /events/watch`                           |
| 404  | No job with that id (jobs are lost when the server restarts)    | `/recommend/{job_id}/status`, `/results`       |
| 409  | The job has not finished; poll `/status` and ask again          | `/recommend/{job_id}/results`                  |
| 422  | The request was invalid; `detail` names the field and the rule  | `POST /recommend`, `/events/watch`, `/movies/search` |
| 500  | The job failed on the server; the details are in the app's log  | `/recommend/{job_id}/results`                  |
| 503  | Qdrant is unreachable or the movies have not been loaded        | `/ready`                                       |

`POST /recommend` takes 1 to 6 descriptions, each 1 to 1000 characters and not blank, and a `top_k` from 1 to 20.

## Usage logs

The app appends usage events to `events.jsonl`, one JSON object per line, in `LOG_DIR` (`logs/` when run locally, the
`logs` volume in Docker). Each tap of the "We're watching ..." button is recorded as

```json
{"ts": "2026-11-06T20:15:00.123456+00:00", "event": "watch_click", "job_id": "...", "movie_id": "546554"}
```

To count the clicks on a running deployment:

```bash
docker compose exec app grep -c '"watch_click"' /logs/events.jsonl
```

## Deploying on Jetstream2

On the instance (an `m3.small` is enough):

```bash
git clone https://github.com/rvt9bx/dsan6700-project.git && cd dsan6700-project
cp .env.deploy.example .env          # then put the real TMDB_API_KEY in .env
docker compose up -d --build
```

`.env.deploy.example` sets `COMPOSE_PROFILES=proxy`, so Caddy starts too and serves the app over HTTPS at
`MOVIEREC_DOMAIN`, with a Let's Encrypt certificate it gets and renews on its own. In Exosphere, the instance's
firewall must allow ports 80 and 443.

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

From outside, only ports 80 and 443 answer: the app's 8080 listens on the instance itself only (`APP_BIND=127.0.0.1`),
and Qdrant is not published at all. To check, on the instance:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

You should see `0.0.0.0:80` and `0.0.0.0:443` for caddy, `127.0.0.1:8080` for app, and nothing for qdrant. From your
laptop:

```bash
curl -I http://team01-app.cis240466.projects.jetstream-cloud.org            # 308, Location: https://...
curl https://team01-app.cis240466.projects.jetstream-cloud.org/ready        # {"status":"ready"}
curl -m 5 http://team01-app.cis240466.projects.jetstream-cloud.org:8080     # Failed to connect
```

The containers restart on their own after a reboot or unshelve, but shelving releases the public IP, so use the
instance's hostname rather than its IP.

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
