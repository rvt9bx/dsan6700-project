import requests

from movierec.config import settings

BASE_URL = settings.tmdb_base_url


def _get_api_key() -> str:
    """Return the TMDB API key at request time rather than import time."""
    if settings.tmdb_api_key is not None:
        api_key = settings.tmdb_api_key.get_secret_value()
        if api_key:
            return api_key
    raise ValueError("Missing TMDB API key")


def get_movie_id(movie_title: str, year: int | None = None) -> int | None:
    """Search for a movie title and return its TMDB ID."""
    url = f"{BASE_URL}/search/movie"

    params = {
        "api_key": _get_api_key(),
        "query": movie_title,
    }
    if year:
        params["primary_release_year"] = str(year)

    response = requests.get(url, params=params).json()
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
    return requests.get(url, params=params).json()
