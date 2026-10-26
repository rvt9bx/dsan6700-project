# movierec: one app container, the API and the page it serves.
#
# Build and run with Compose:  docker compose up -d --build   (http://<host>:8080)
#
# Where things live (decided 2026-10, see docs/ARCHITECTURE.md):
#   the API + UI    this image: FastAPI serves the HTML/JS frontend from src/movierec/ui, so there is
#                   no separate frontend to deploy
#   the model       in-process, CPU only, so a slim Python base and no CUDA image
#   the vectors     Qdrant, in its own container on the internal Compose network (added once retrieval
#                   is real); only this container's port 8080 is published
#   configuration   the environment at run time (.env through Compose), never copied into the image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never

# Install uv (pinned version for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

# Non-root user to run the service
RUN useradd --create-home --uid 1000 app

WORKDIR /app

# Install dependencies from the lock file before copying the source, so this
# layer is cached and only rebuilds when pyproject.toml or uv.lock change
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy the source and install the project itself
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

USER app

EXPOSE 8080

# The image has no curl; Python asks the readiness endpoint itself. The start
# period gives the model time to load once it is baked in.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ready', timeout=4)"

CMD ["/app/.venv/bin/uvicorn", "movierec.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
