"""Who may call routes that are not for every user, such as /metrics."""

import secrets

from fastapi import HTTPException, Request

from movierec.config import settings

_BEARER = "bearer "


def require_operator(request: Request) -> None:
    """Allow the call only with `Authorization: Bearer <METRICS_TOKEN>`.

    401 when the token is missing or wrong, so the caller knows to authenticate;
    403 when no token is configured, because then nobody is allowed. The comparison
    takes the same time whatever the token, so it cannot be guessed a character at
    a time.
    """
    expected = settings.metrics_token
    if expected is None:
        raise HTTPException(
            status_code=403,
            detail="This route is disabled: set METRICS_TOKEN on the server to enable it.",
        )

    header = request.headers.get("Authorization", "")
    supplied = header[len(_BEARER) :] if header.lower().startswith(_BEARER) else ""
    if not secrets.compare_digest(
        supplied.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(
            status_code=401,
            detail="Send the operator token as 'Authorization: Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
