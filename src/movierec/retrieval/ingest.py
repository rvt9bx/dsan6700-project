"""movierec-ingest: read the TMDB movies Parquet, clean it, embed it, and store it in Qdrant.

Usage:
    movierec-ingest                      # index everything not already stored
    movierec-ingest --limit 500          # try a small slice first
    movierec-ingest --reindex            # re-embed movies already stored (after editing text.py)
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable
from itertools import islice
from pathlib import Path

from movierec.retrieval import MovieDoc, Retriever
from movierec.retrieval.data import (
    MovieRecord,
    iter_movies,
    movie_to_payload,
    movie_to_text,
)

logger = logging.getLogger(__name__)


def _load_settings():
    """Load project settings."""
    try:
        from movierec.config import settings
    except ImportError as exc:
        raise SystemExit("Could not import settings from movierec.config") from exc
    return settings


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="movierec-ingest",
        description="Embed the TMDB movies Parquet into Qdrant.",
    )
    p.add_argument(
        "--parquet",
        type=Path,
        help="Parquet/CSV path (default: MOVIES_PATH from settings)",
    )
    p.add_argument("--limit", type=int, help="only process the first N cleaned movies")
    p.add_argument(
        "--reindex", action="store_true", help="re-embed movies that are already stored"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    settings = _load_settings()
    data_path = args.parquet or Path(settings.movies_path)
    records: Iterable[MovieRecord] = iter_movies(data_path)
    if args.limit:
        records = islice(records, args.limit)

    retriever = Retriever.from_settings(settings)
    retriever.warmup()
    retriever.store.ensure_collection()

    def docs():
        for r in records:
            yield MovieDoc(
                tmdb_id=r.tmdb_id, text=movie_to_text(r), payload=movie_to_payload(r)
            )

    indexed = retriever.index(docs(), skip_existing=not args.reindex)
    logger.info(f"Finished ingestion, {indexed} in collection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
