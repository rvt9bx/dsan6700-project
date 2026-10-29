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
