"""Loguru setup shared by the API and the command-line jobs.

Every line is one JSON object with flat fields, so a tool can search by any of them:

    docker compose logs app --no-log-prefix | jq 'select(.request_id == "...")'

Log ids, counts, lengths and timings. Never log a user's descriptions, a model's
answer, a file name or a secret.
"""

from __future__ import annotations

import inspect
import json
import logging
import sys
import traceback
from types import FrameType
from typing import TYPE_CHECKING

from loguru import logger

from movierec.config import settings

if TYPE_CHECKING:
    from loguru import Record

APP_LOG_FILENAME = "app.jsonl"
LOG_FILE_ROTATION = "50 MB"
LOG_FILE_RETENTION = 5  # rotated files kept, so the logs volume tops out near 300 MB

TEXT_FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green> <level>{level: <8}</level> "
    "<cyan>{name}</cyan>: {message} <dim>{extra}</dim>"
)


def json_line(record: Record) -> str:
    """One log record as a flat JSON object: the standard fields, then the bound fields."""
    entry: dict[str, object] = {
        "ts": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "logger": record["name"],
        "function": record["function"],
        "line": record["line"],
    }
    entry.update({k: v for k, v in record["extra"].items() if not k.startswith("_")})
    if record["exception"] is not None:
        exc_type, exc_value, tb = record["exception"]
        entry["exception"] = "".join(
            traceback.format_exception(exc_type, exc_value, tb)
        )
    return json.dumps(entry, default=str)


def _json_format(record: Record) -> str:
    """Loguru format function: store the JSON line in the record and print only that."""
    record["extra"]["_json"] = json_line(record)
    return "{extra[_json]}\n"


class InterceptHandler(logging.Handler):
    """Send records from the standard logging module (uvicorn, qdrant-client) to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        """Re-log the record through loguru at the same level, from the original caller."""
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Step out of this method and the logging module to the code that logged
        frame: FrameType | None = inspect.currentframe()
        depth = 0
        while frame is not None and (
            depth == 0 or frame.f_code.co_filename == logging.__file__
        ):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_logging(log_file: bool = True) -> None:
    """Send all logs to stdout, and also to LOG_DIR/app.jsonl when log_file is True.

    The file outlives the container (it is on the logs volume), so request logs
    survive a redeploy; it rotates at LOG_FILE_ROTATION so it cannot fill the disk.
    diagnose=False keeps variable values, which may hold user text, out of tracebacks.
    """
    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format=_json_format if settings.log_json else TEXT_FORMAT,
        backtrace=False,
        diagnose=False,
    )
    if log_file:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            settings.log_dir / APP_LOG_FILENAME,
            level=settings.log_level,
            format=_json_format,
            rotation=LOG_FILE_ROTATION,
            retention=LOG_FILE_RETENTION,
            backtrace=False,
            diagnose=False,
        )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = []
        std_logger.propagate = True
    # Our middleware writes one line per request with a request id instead. uvicorn's
    # access line would also print query strings, which can hold a user's text
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.disabled = True
    # qdrant-client logs every HTTP call it makes at INFO
    logging.getLogger("httpx").setLevel(logging.WARNING)
