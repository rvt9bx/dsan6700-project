"""Rules every request goes through: body size and type on the way in, caching on the way out."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from movierec.config import settings

BODY_METHODS = {"POST", "PUT", "PATCH"}
JSON_MEDIA_TYPE = "application/json"

# For /static URLs carrying a content hash (?v=...): the file at that URL never changes
LONG_LIVED = "public, max-age=31536000, immutable"
# The page itself, and /static URLs without a hash: cache, but check for a new version first
REVALIDATE = "no-cache"
# API answers can belong to one user, so no browser or shared cache may keep them
NO_STORE = "no-store"


def body_problem(request: Request) -> JSONResponse | None:
    """The error response for a request body we will not read, or None if it is fine.

    411 when a body is sent without saying how long it is, 413 when it is over
    MAX_BODY_BYTES, and 415 when it is not JSON. Checked from the headers alone,
    before any of the body is read.
    """
    if request.method not in BODY_METHODS:
        return None

    length_header = request.headers.get("content-length")
    if length_header is None:
        if "transfer-encoding" in request.headers:
            return _error(411, "Send a Content-Length header with the request body.")
        length = 0
    else:
        try:
            length = int(length_header)
        except ValueError:
            return _error(400, "The Content-Length header must be a whole number.")

    if length > settings.max_body_bytes:
        return _error(
            413,
            f"The request body is {length} bytes; the limit is "
            f"{settings.max_body_bytes} bytes.",
        )

    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != JSON_MEDIA_TYPE:
        return _error(
            415, "Send the request body as JSON, with 'Content-Type: application/json'."
        )
    return None


def cache_control_for(request: Request) -> str:
    """The Cache-Control header for a response to this request."""
    path = request.url.path
    if path.startswith("/static/"):
        return LONG_LIVED if request.query_params.get("v") else REVALIDATE
    if path == "/":
        return REVALIDATE
    return NO_STORE


async def apply_request_policies(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Turn away bodies we will not read, and set Cache-Control on every response."""
    response = body_problem(request) or await call_next(request)
    response.headers.setdefault("Cache-Control", cache_control_for(request))
    return response


def _error(status: int, detail: str) -> JSONResponse:
    """A JSON error in the same shape as FastAPI's own: {"detail": ...}."""
    return JSONResponse(status_code=status, content={"detail": detail})
