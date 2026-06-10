"""Tests for TMDB adapter -- HTTP boundary for TMDB API v3."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.adapters.tmdb import TMDBAdapter, TMDBError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_httpx(json_data, *, status_code=200):
    """Patch ``httpx.Client`` so its ``.get()`` returns *json_data*.

    Returns ``(patcher, mock_client)`` for optional assertion.
    """
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.json.return_value = json_data
    mock_resp.status_code = status_code

    mock_cli = MagicMock()
    mock_cli.__enter__.return_value = mock_cli
    mock_cli.get.return_value = mock_resp

    return patch("httpx.Client", return_value=mock_cli), mock_cli


def _adapter(**kwargs):
    defaults = {"api_key": "tmdb_test_key"}
    defaults.update(kwargs)
    return TMDBAdapter(**defaults)


# ---------------------------------------------------------------------------
# TestTMDBAdapterInit
# ---------------------------------------------------------------------------

class TestTMDBAdapterInit:
    def test_default_base_url(self):
        adapter = _adapter()
        assert adapter.base_url == "https://api.themoviedb.org"
        assert adapter.api_key == "tmdb_test_key"
        assert adapter.timeout_seconds == 10.0

    def test_custom_base_url(self):
        adapter = _adapter(base_url="https://custom.tmdb.org")
        assert adapter.base_url == "https://custom.tmdb.org"


# ---------------------------------------------------------------------------
# TestTMDBAdapterSearchMulti
# ---------------------------------------------------------------------------

class TestTMDBAdapterSearchMulti:
    def test_returns_parsed_json(self):
        """Successful search_multi returns the full TMDB response dict."""
        mock_data = {
            "page": 1,
            "results": [{"id": 1, "media_type": "movie", "title": "Dune"}],
            "total_pages": 1,
            "total_results": 1,
        }
        patcher, _mock_client = _mock_httpx(mock_data)
        with patcher:
            result = _adapter().search_multi("Dune")
        assert result == mock_data

    def test_correct_url_and_params(self):
        """URL path, api_key, language, query, page, include_adult are sent."""
        patcher, mock_cli = _mock_httpx({"page": 1, "results": []})
        with patcher:
            _adapter().search_multi("Dune", page=2, include_adult=True)

        mock_cli.get.assert_called_once()
        args, kwargs = mock_cli.get.call_args
        assert args[0] == "https://api.themoviedb.org/3/search/multi"
        params = kwargs["params"]
        assert params["api_key"] == "tmdb_test_key"
        assert params["language"] == "zh-CN"
        assert params["query"] == "Dune"
        assert params["page"] == 2
        assert params["include_adult"] is True

    def test_default_page_and_adult(self):
        """Defaults page=1, include_adult=False."""
        patcher, mock_cli = _mock_httpx({"page": 1, "results": []})
        with patcher:
            _adapter().search_multi("Dune")

        _, kwargs = mock_cli.get.call_args
        params = kwargs["params"]
        assert params["page"] == 1
        assert params["include_adult"] is False

    def test_http_error_raises_tmdb_error(self):
        """HTTP errors from httpx propagate as TMDBError."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=mock_resp,
        )
        mock_cli = MagicMock()
        mock_cli.__enter__.return_value = mock_cli
        mock_cli.get.return_value = mock_resp
        with patch("httpx.Client", return_value=mock_cli):
            with pytest.raises(TMDBError):
                _adapter().search_multi("Dune")

    def test_not_configured_returns_empty(self):
        """Empty api_key returns empty paginated response."""
        result = _adapter(api_key="").search_multi("Dune")
        assert result == {
            "page": 1,
            "results": [],
            "total_pages": 0,
            "total_results": 0,
        }

    def test_not_configured_whitespace_key(self):
        """Whitespace-only api_key is treated as not configured."""
        result = _adapter(api_key="   ").search_multi("Dune")
        assert result["results"] == []


# ---------------------------------------------------------------------------
# TestTMDBAdapterMovieDetails
# ---------------------------------------------------------------------------

class TestTMDBAdapterMovieDetails:
    def test_append_to_response_includes_external_ids(self):
        """append_to_response=external_ids and zh-CN are always present."""
        mock_data = {
            "id": 693134,
            "title": "Dune: Part Two",
            "external_ids": {"imdb_id": "tt15239678"},
        }
        patcher, mock_cli = _mock_httpx(mock_data)
        with patcher:
            result = _adapter().movie_details(693134)

        assert result == mock_data
        _, kwargs = mock_cli.get.call_args
        params = kwargs["params"]
        assert params["append_to_response"] == "external_ids"
        assert params["language"] == "zh-CN"

    def test_url_includes_movie_id(self):
        """URL path contains the movie id."""
        patcher, mock_cli = _mock_httpx({"id": 693134})
        with patcher:
            _adapter().movie_details(693134)

        args, _ = mock_cli.get.call_args
        assert args[0] == "https://api.themoviedb.org/3/movie/693134"

    def test_not_configured_returns_empty_dict(self):
        result = _adapter(api_key="").movie_details(693134)
        assert result == {}


# ---------------------------------------------------------------------------
# TestTMDBAdapterTvDetails
# ---------------------------------------------------------------------------

class TestTMDBAdapterTvDetails:
    def test_append_to_response_includes_external_ids(self):
        """Same append_to_response for tv details."""
        mock_data = {
            "id": 1399,
            "name": "Game of Thrones",
            "external_ids": {"imdb_id": "tt0944947"},
        }
        patcher, mock_cli = _mock_httpx(mock_data)
        with patcher:
            result = _adapter().tv_details(1399)

        assert result == mock_data
        _, kwargs = mock_cli.get.call_args
        assert kwargs["params"]["append_to_response"] == "external_ids"
        assert kwargs["params"]["language"] == "zh-CN"

    def test_url_includes_series_id(self):
        patcher, mock_cli = _mock_httpx({"id": 1399})
        with patcher:
            _adapter().tv_details(1399)

        args, _ = mock_cli.get.call_args
        assert args[0] == "https://api.themoviedb.org/3/tv/1399"

    def test_not_configured_returns_empty_dict(self):
        result = _adapter(api_key="").tv_details(1399)
        assert result == {}


# ---------------------------------------------------------------------------
# TestTMDBAdapterDiscover
# ---------------------------------------------------------------------------

class TestTMDBAdapterDiscover:
    def test_discover_movie_passes_filters(self):
        """Filters like sort_by, with_genres, release year, vote count are sent."""
        filters = {
            "sort_by": "popularity.desc",
            "with_genres": "28",
            "primary_release_year": 2024,
            "vote_count_gte": 100,
        }
        patcher, mock_cli = _mock_httpx({"page": 1, "results": []})
        with patcher:
            _adapter().discover_movie(**filters)

        args, kwargs = mock_cli.get.call_args
        assert args[0] == "https://api.themoviedb.org/3/discover/movie"
        params = kwargs["params"]
        assert params["sort_by"] == "popularity.desc"
        assert params["with_genres"] == "28"
        assert params["primary_release_year"] == 2024
        assert params["vote_count_gte"] == 100
        assert params["language"] == "zh-CN"

    def test_discover_tv_passes_filters(self):
        """TV discovery sends first_air_date_year and other filters."""
        filters = {"first_air_date_year": 2023, "with_genres": "18"}
        patcher, mock_cli = _mock_httpx({"page": 1, "results": []})
        with patcher:
            _adapter().discover_tv(**filters)

        args, kwargs = mock_cli.get.call_args
        assert args[0] == "https://api.themoviedb.org/3/discover/tv"
        params = kwargs["params"]
        assert params["first_air_date_year"] == 2023
        assert params["with_genres"] == "18"

    def test_discover_movie_no_filters(self):
        """No filters still works and sends api_key + language."""
        patcher, mock_cli = _mock_httpx({"page": 1, "results": []})
        with patcher:
            _adapter().discover_movie()

        _, kwargs = mock_cli.get.call_args
        params = kwargs["params"]
        assert params["api_key"] == "tmdb_test_key"
        assert params["language"] == "zh-CN"
        assert len(params) == 2  # only api_key + language

    def test_not_configured_returns_empty(self):
        result = _adapter(api_key="").discover_movie(sort_by="popularity.desc")
        assert result["results"] == []


# ---------------------------------------------------------------------------
# TestTMDBAdapterTrending
# ---------------------------------------------------------------------------

class TestTMDBAdapterTrending:
    def test_default_time_window_is_day(self):
        """trending_all defaults to day window."""
        patcher, mock_cli = _mock_httpx({"page": 1, "results": []})
        with patcher:
            _adapter().trending_all()

        args, _ = mock_cli.get.call_args
        assert args[0] == "https://api.themoviedb.org/3/trending/all/day"

    def test_custom_time_window(self):
        """Passing time_window=week changes the URL path."""
        patcher, mock_cli = _mock_httpx({"page": 1, "results": []})
        with patcher:
            _adapter().trending_all(time_window="week")

        args, _ = mock_cli.get.call_args
        assert args[0] == "https://api.themoviedb.org/3/trending/all/week"

    def test_language_zh_cn_always_present(self):
        patcher, mock_cli = _mock_httpx({"page": 1, "results": []})
        with patcher:
            _adapter().trending_all()

        _, kwargs = mock_cli.get.call_args
        assert kwargs["params"]["language"] == "zh-CN"

    def test_not_configured_returns_empty(self):
        result = _adapter(api_key="").trending_all()
        assert result == {
            "page": 1,
            "results": [],
            "total_pages": 0,
            "total_results": 0,
        }


# ---------------------------------------------------------------------------
# TestTMDBAdapterHealth
# ---------------------------------------------------------------------------

class TestTMDBAdapterHealth:
    def test_returns_ok_on_success(self):
        """health() returns "ok" when GET /3/authentication succeeds."""
        mock_data = {"success": True}
        patcher, mock_cli = _mock_httpx(mock_data)
        with patcher:
            result = _adapter().health()

        assert result == "ok"
        args, _ = mock_cli.get.call_args
        assert args[0] == "https://api.themoviedb.org/3/authentication"

    def test_returns_error_on_4xx(self):
        """health() returns "error" on 401 (bad credentials)."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=mock_resp,
        )
        mock_cli = MagicMock()
        mock_cli.__enter__.return_value = mock_cli
        mock_cli.get.return_value = mock_resp
        with patch("httpx.Client", return_value=mock_cli):
            result = _adapter().health()

        assert result == "error"

    def test_returns_unavailable_on_5xx(self):
        """health() returns "unavailable" on 500 (server-side failure)."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error", request=MagicMock(), response=mock_resp,
        )
        mock_cli = MagicMock()
        mock_cli.__enter__.return_value = mock_cli
        mock_cli.get.return_value = mock_resp
        with patch("httpx.Client", return_value=mock_cli):
            result = _adapter().health()

        assert result == "unavailable"

    def test_returns_unavailable_on_connect_error(self):
        """health() returns "unavailable" on connection failure."""
        mock_cli = MagicMock()
        mock_cli.__enter__.return_value = mock_cli
        mock_cli.get.side_effect = httpx.ConnectError("Connection refused")
        with patch("httpx.Client", return_value=mock_cli):
            result = _adapter().health()

        assert result == "unavailable"

    def test_returns_unconfigured_when_not_configured(self):
        result = _adapter(api_key="").health()
        assert result == "unconfigured"


# ---------------------------------------------------------------------------
# TestTMDBAdapterError
# ---------------------------------------------------------------------------

class TestTMDBErrorType:
    """TMDBError is a proper Exception subclass that can be raised and caught."""

    def test_is_exception_subclass(self):
        assert issubclass(TMDBError, Exception)

    def test_can_raise_and_catch(self):
        try:
            raise TMDBError("test error")
        except TMDBError as exc:
            assert str(exc) == "test error"

    def test_preserves_cause(self):
        cause = ValueError("original")
        try:
            try:
                raise cause
            except ValueError:
                raise TMDBError("wrapped") from cause
        except TMDBError as exc:
            assert exc.__cause__ is cause
