"""TMDB API client helpers for movie search and metadata retrieval."""

from __future__ import annotations

import logging
import time

import requests

from movierec.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
BASE_URL = settings.tmdb_base_url


def _get_api_key() -> str:
    """Return the TMDB API key at request time rather than import time."""
    if settings.tmdb_api_key is not None:
        api_key = settings.tmdb_api_key.get_secret_value()
        if api_key:
            return api_key
    raise ValueError("Missing TMDB API key")


def _get_json_with_retry(
    url: str,
    params: dict,
    max_retries: int = 4,
    base_backoff: float = 1.0,
) -> dict:
    """Perform a GET request with exponential backoff on transient failures."""
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params)
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
                retry_after = response.headers.get("Retry-After")
                sleep_s = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else base_backoff * (2**attempt)
                )
                logger.warning(
                    "TMDB returned %s for %s; retrying in %.1fs (attempt %d/%d)",
                    response.status_code,
                    url,
                    sleep_s,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(sleep_s)
                continue

            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError:
            # Do not retry non-retryable HTTP errors (e.g., 404)
            raise
        except (requests.exceptions.RequestException, ValueError) as e:
            if attempt >= max_retries:
                raise
            sleep_s = base_backoff * (2**attempt)
            logger.warning(
                "Request/JSON error for %s (%s); retrying in %.1fs (attempt %d/%d)",
                url,
                e,
                sleep_s,
                attempt + 1,
                max_retries,
            )
            time.sleep(sleep_s)

    return {}


def get_movie_id(movie_title: str, year: int | None = None) -> int | None:
    """Search for a movie title and return its TMDB ID."""
    url = f"{BASE_URL}/search/movie"

    params = {
        "api_key": _get_api_key(),
        "query": movie_title,
    }
    if year:
        params["primary_release_year"] = str(year)

    response = _get_json_with_retry(url, params=params)
    results = response.get("results", [])
    return results[0]["id"] if results else None


def get_movie_info(movie_title: str, year: int | None = None) -> dict:
    """Fetch overview and genres using get_movie_id."""
    movie_id = get_movie_id(movie_title, year)
    if not movie_id:
        return {
            "movie_id": None,
            "overview": None,
            "genres": [],
        }

    url = f"{BASE_URL}/movie/{movie_id}"
    params = {
        "api_key": _get_api_key(),
    }
    return _get_json_with_retry(url, params=params)
