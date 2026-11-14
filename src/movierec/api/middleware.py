"""Request ids, and one summary log line for every request."""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.routing import Match

from movierec.api import metrics
from movierec.config import settings

REQUEST_ID_HEADER = "X-Request-ID"
# A caller's id is reused only if it is short and plain, so it is safe to log and echo
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
MAX_LOGGED_JOB_ID = 64
# Methods get their own metric label; anything else is counted as OTHER
KNOWN_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}

UNEXPECTED_ERROR = (
    "The server hit an unexpected error. Please try again, and quote the request id "
    "if you report it."
)


def request_id_from(header_value: str | None) -> str:
    """The caller's X-Request-ID if it is safe to reuse, otherwise a new id."""
    if header_value and _SAFE_REQUEST_ID.fullmatch(header_value):
        return header_value
    return uuid4().hex


def endpoint_of(request: Request) -> str:
    """The route a request is for, e.g. /recommend/{job_id}/status, rather than its path.

    Using the template keeps ids out of the field, so it can be grouped and counted.
    Call it before the request is handled: routing rewrites the scope it matches on.
    Matching here also names the route of a request turned away before routing (a 413,
    say). Files under /static are reported as /static, and unknown paths as "unmatched".
    """
    for route in request.app.router.routes:
        match, _ = route.matches(request.scope)
        if match is not Match.NONE:
            return getattr(route, "path", None) or "unmatched"
    return "unmatched"


def _level_for(status: int) -> str:
    """ERROR when the service failed, WARNING when the caller did, INFO otherwise."""
    if status >= 500:
        return "ERROR"
    if status >= 400:
        return "WARNING"
    return "INFO"


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Give the request an id, log one line when it finishes, and return the id.

    Every log line written while handling the request, in any module, carries the same
    request_id, because loguru's contextualize stores it in a context variable.
    """
    request_id = request_id_from(request.headers.get(REQUEST_ID_HEADER))
    started = time.perf_counter()
    endpoint = endpoint_of(request)
    with logger.contextualize(request_id=request_id):
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled error")
            response = JSONResponse(
                status_code=500,
                content={"detail": UNEXPECTED_ERROR, "request_id": request_id},
            )

        seconds = time.perf_counter() - started
        method = request.method if request.method in KNOWN_METHODS else "OTHER"
        metrics.HTTP_REQUESTS.labels(endpoint, method, str(response.status_code)).inc()
        metrics.HTTP_REQUEST_SECONDS.labels(endpoint, method).observe(seconds)
        fields: dict[str, object] = {
            "method": request.method,
            "endpoint": endpoint,
            "status": response.status_code,
            "duration_ms": round(seconds * 1000, 1),
        }
        job_id = request.scope.get("path_params", {}).get("job_id")
        if job_id:
            fields["job_id"] = str(job_id)[:MAX_LOGGED_JOB_ID]
        if endpoint.startswith("/recommend"):
            fields["model"] = settings.embed_model
        logger.bind(**fields).log(_level_for(response.status_code), "Request finished")

    response.headers[REQUEST_ID_HEADER] = request_id
    return response
