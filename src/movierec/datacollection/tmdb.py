import requests

from movierec.config import settings


if settings.tmdb_api_key is not None:
    TMDB_API_KEY = settings.tmdb_api_key.get_secret_value()
else:
    raise ValueError("Missing TMDB API key")

BASE_URL = settings.tmdb_base_url


def get_movie_id(movie_title: str, year: int | None = None) -> int | None:
    """Search for a movie title and return its TMDB ID."""
    url = f"{BASE_URL}/search/movie"

    params = {
        "api_key": TMDB_API_KEY,
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
        "api_key": (
            TMDB_API_KEY.get_secret_value()
            if hasattr(TMDB_API_KEY, "get_secret_value")
            else TMDB_API_KEY
        ),
        "append_to_response": "credits",
    }
    return requests.get(url, params=params).json()


def get_poster_path(
    movie_title: str, year: int | None = None, size: str = "w500"
) -> str | None:
    """Fetch poster URL using get_movie_id."""
    movie_id = get_movie_id(movie_title, year)
    if not movie_id:
        return None

    url = f"{BASE_URL}/movie/{movie_id}"
    params = {
        "api_key": (
            TMDB_API_KEY.get_secret_value()
            if hasattr(TMDB_API_KEY, "get_secret_value")
            else TMDB_API_KEY
        )
    }
    response = requests.get(url, params=params).json()
    poster_path = response.get("poster_path")

    return f"https://image.tmdb.org/t/p/{size}{poster_path}" if poster_path else None
