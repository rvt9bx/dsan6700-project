"""Usage events for monitoring, appended to a JSON Lines file on the logs volume."""

import json
import threading
from datetime import UTC, datetime
from typing import Any

from movierec.config import settings

EVENTS_FILENAME = "events.jsonl"

# Endpoints run in a thread pool, so keep concurrent writes from interleaving
_write_lock = threading.Lock()


def record_event(event: str, **fields: Any) -> None:
    """Append one event, stamped with the current UTC time, to the events file."""
    entry = {"ts": datetime.now(UTC).isoformat(), "event": event, **fields}
    path = settings.log_dir / EVENTS_FILENAME
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
