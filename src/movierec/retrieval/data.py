"""Read the TMDB movies Parquet/CSV, clean rows, build embedding text & payload."""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("tmdb_id", "title", "overview")


@dataclass(frozen=True)
class MovieRecord:
    """One cleaned movie."""

    tmdb_id: int
    title: str
    overview: str
    year: int | None = None
    genres: list[str] = field(default_factory=list)
    poster_path: str | None = None
    popularity: float | None = None
    runtime: float | None = None


# ---------------------------------------------------------------- parsing helpers
def clean_text(value: object) -> str:
    """Collapse all whitespace (including newlines) to single spaces. Returns '' for None/NaN."""
    if value is None:
        return ""
    if isinstance(value, float):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_int(value: str | None) -> int | None:
    s = (value or "").strip()
    return int(s) if s else None


def parse_float(value: str | None) -> float | None:
    try:
        f = float(value or "")
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_year(release_date: str | None, year_value: str | None = None) -> int | None:
    """Year from a 'YYYY-MM-DD' date, falling back to a separate year column."""
    if release_date:
        try:
            return int(release_date[:4])
        except (ValueError, IndexError):
            pass
    if year_value:
        try:
            return int(year_value)
        except ValueError:
            pass
    return None


def parse_genres(raw: object) -> list[str]:
    """Genres as a clean list, whatever the format.

    Accepts:
    - JSON array: '["Drama", "Comedy"]'
    - Python repr: "[{'id': 18, 'name': 'Drama'}, ...]"
    - CSV like: "Drama, Comedy"
    """
    if raw is None:
        return []
    if isinstance(raw, float):
        return []
    s = str(raw).strip()
    if not s or s == "[]":
        return []

    # Try JSON array first: ["Drama", "Comedy"]
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            # Handle both ["Drama"] and [{"name": "Drama"}]
            genres = []
            for item in parsed:
                if isinstance(item, str):
                    genres.append(item)
                elif isinstance(item, dict) and "name" in item:
                    genres.append(str(item["name"]))
            return genres
    except json.JSONDecodeError:
        pass

    # Fallback: split on comma
    return [g.strip() for g in s.split(",") if g.strip()]


# ---------------------------------------------------------------- row cleaning
def clean_row(row: pd.Series) -> MovieRecord | None:
    """Return MovieRecord or None if required fields missing."""
    tmdb_id = row.get("tmdb_id")
    if pd.isna(tmdb_id) or tmdb_id == "":
        return None

    title = clean_text(row.get("title"))
    overview = clean_text(row.get("overview"))
    if not title or not overview:
        return None

    record = MovieRecord(
        tmdb_id=int(float(tmdb_id)),
        title=title,
        overview=overview,
        year=parse_year(row.get("release_date"), row.get("year")),
        genres=parse_genres(row.get("genres")),
        poster_path=clean_text(row.get("poster_path")) or None,
        popularity=parse_float(row.get("popularity")),
        runtime=parse_float(row.get("runtime")),
    )
    return record


def iter_movies(file_path: str | Path) -> Iterator[MovieRecord]:
    """Stream cleaned movies from Parquet or CSV."""
    path = Path(file_path)
    if path.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    for _, row in df.iterrows():
        record = clean_row(row)
        if record:
            yield record


# ---------------------------------------------------------------- text & payload
TEXT_VERSION = "v1"


def _sentence(s: str) -> str:
    """Make sure a fragment ends with sentence punctuation."""
    return s if s.endswith((".", "!", "?", "…")) else s + "."


def movie_to_text(m: MovieRecord) -> str:
    """Build the exact string that gets embedded.

    Format: "Title (Year). Genres: a, b. Popularity. Overview"
    """
    head = f"{m.title} ({m.year})" if m.year else m.title
    parts = [_sentence(head)]
    if m.genres:
        parts.append(f"Genres: {', '.join(m.genres)}.")
    if m.popularity is not None:
        parts.append(_sentence(str(m.popularity)))
    parts.append(m.overview)
    return " ".join(parts)


def movie_to_payload(m: MovieRecord) -> dict[str, object]:
    """Metadata stored beside the vector (JSON-serializable)."""
    return {
        "title": m.title,
        "year": m.year,
        "genres": list(m.genres),
        "overview": m.overview,
        "poster_path": m.poster_path,
        "popularity": m.popularity,
        "runtime": m.runtime,
        "text_version": TEXT_VERSION,
    }
