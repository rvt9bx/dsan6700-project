"""Tests for movierec.datacollection.tmdb module."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from movierec.datacollection.tmdb import get_movie_id, get_movie_info


class TestGetMovieId:
    """Tests for get_movie_id function."""

    @patch("movierec.datacollection.tmdb.requests.get")
    def test_returns_first_result_id(self, mock_get):
        """Returns the ID of the first search result."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"id": 546554}, {"id": 123456}]}
        mock_get.return_value = mock_resp

        result = get_movie_id("Knives Out", 2019)

        assert result == 546554
        _args, kwargs = mock_get.call_args
        assert kwargs["params"]["query"] == "Knives Out"
        assert kwargs["params"]["primary_release_year"] == "2019"

    @patch("movierec.datacollection.tmdb.requests.get")
    def test_returns_none_when_no_results(self, mock_get):
        """Returns None when search returns no results."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_get.return_value = mock_resp

        result = get_movie_id("Nonexistent Movie xyz", 2020)

        assert result is None

    @patch("movierec.datacollection.tmdb.requests.get")
    def test_omits_year_param_when_none(self, mock_get):
        """Does not include primary_release_year when year is None."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"id": 1}]}
        mock_get.return_value = mock_resp

        get_movie_id("Movie", None)

        _args, kwargs = mock_get.call_args
        assert "primary_release_year" not in kwargs["params"]

    @patch("movierec.datacollection.tmdb.requests.get")
    def test_raises_on_http_error(self, mock_get):
        """Propagates HTTP errors from the API."""
        mock_get.side_effect = requests.exceptions.HTTPError("404 Not Found")

        with pytest.raises(requests.exceptions.HTTPError):
            get_movie_id("Movie", 2020)


class TestGetMovieInfo:
    """Tests for get_movie_info function."""

    @patch("movierec.datacollection.tmdb.get_movie_id")
    @patch("movierec.datacollection.tmdb.requests.get")
    def test_returns_full_movie_response(self, mock_get, mock_get_id):
        """Returns the full movie detail response from TMDB."""
        mock_get_id.return_value = 546554
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": 546554,
            "title": "Knives Out",
            "overview": "A detective untangles a wealthy family's alibis.",
            "genres": [{"id": 35, "name": "Comedy"}, {"id": 80, "name": "Crime"}],
            "poster_path": "/pThyQovXQrw2m0s9x82twj48Jq4.jpg",
            "runtime": 130,
        }
        mock_get.return_value = mock_resp

        result = get_movie_info("Knives Out", 2019)

        assert result["id"] == 546554
        assert result["title"] == "Knives Out"
        assert "overview" in result
        assert len(result["genres"]) == 2
        mock_get.assert_called_once_with(
            f"{__import__('movierec.config').config.settings.tmdb_base_url}/movie/546554",
            params={
                "api_key": __import__(
                    "movierec.config"
                ).config.settings.tmdb_api_key.get_secret_value()
            },
        )

    @patch("movierec.datacollection.tmdb.get_movie_id")
    def test_returns_empty_dict_when_no_movie_id(self, mock_get_id):
        """Returns minimal dict with None/empty values when movie not found."""
        mock_get_id.return_value = None

        result = get_movie_info("Nonexistent", 2020)

        assert result == {"movie_id": None, "overview": None, "genres": []}


class TestTmdbApiKey:
    """Tests for TMDB API key handling."""

    def test_settings_tmdb_api_key_none_raises(self):
        """SecretStr.get_secret_value() raises when value is None."""

        from movierec.config import Settings

        settings = Settings(tmdb_api_key=None)
        # The module does: settings.tmdb_api_key.get_secret_value()
        # which raises AttributeError when tmdb_api_key is None
        with pytest.raises(AttributeError):
            settings.tmdb_api_key.get_secret_value()

    def test_settings_tmdb_api_key_works_when_set(self):
        """SecretStr.get_secret_value() returns the key when set."""
        from pydantic import SecretStr

        from movierec.config import Settings

        settings = Settings(tmdb_api_key=SecretStr("test-key"))
        assert settings.tmdb_api_key.get_secret_value() == "test-key"
