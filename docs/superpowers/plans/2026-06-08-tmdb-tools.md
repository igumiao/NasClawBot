# TMDB 工具集实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 4 个 TMDB API v3 工具（tmdb_search, tmdb_details, tmdb_discover, tmdb_trending），通过 TMDBAdapter 封装 HTTP 调用，所有响应使用 zh-CN 中文。

**Architecture:** 遵循现有 mteam adapter + 每工具一文件模式。TMDBAdapter 使用 httpx GET 请求，自动附加 `language=zh-CN` 和 `api_key`。四个工具分别包装对应的 TMDB 端点。

**Tech Stack:** Python, httpx, hello_agents Tool/ToolParameter/ToolResponse, pydantic Settings

---

### Task 1: 配置 — 新增 TMDB_API_KEY

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: 在 Settings 中新增 tmdb_api_key 字段**

在 `app/config.py` 的 `Settings` 类中，`log_level` 字段之后新增：

```python
tmdb_api_key: str = Field(default_factory=lambda: _get_env("TMDB_API_KEY"))
```

- [ ] **Step 2: 验证编译正确**

```bash
.venv/bin/python -m compileall app/config.py -q
```

- [ ] **Step 3: 验证 Settings 能正常加载**

```bash
.venv/bin/python -c "from app.config import get_settings; s = get_settings(); print('tmdb_api_key:', repr(s.tmdb_api_key))"
```

预期：输出 `tmdb_api_key: ''`（未配置 .env 时）或实际值。

- [ ] **Step 4: Commit**

```bash
git add app/config.py
git commit -m "feat: add TMDB_API_KEY to Settings

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: TMDBAdapter — 核心 HTTP 适配器 + 测试

**Files:**
- Create: `app/adapters/tmdb.py`
- Create: `tests/test_tmdb_adapter.py`

- [ ] **Step 1: 创建 `tests/test_tmdb_adapter.py` 测试文件**

```python
"""Tests for TMDBAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.adapters.tmdb import TMDBAdapter, TMDBError


class TestTMDBAdapterInit:
    def test_default_base_url(self):
        adapter = TMDBAdapter(api_key="test_key")
        assert adapter.base_url == "https://api.themoviedb.org"
        assert adapter.api_key == "test_key"

    def test_custom_base_url(self):
        adapter = TMDBAdapter(api_key="key123", base_url="https://custom.example.com")
        assert adapter.base_url == "https://custom.example.com"


class TestTMDBAdapterSearchMulti:
    def test_builds_correct_url_and_params(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"page": 1, "results": []}
            mock_response.raise_for_status.return_value = None
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            adapter.search_multi("沙丘")

            call_args = mock_client.get.call_args
            url = call_args[0][0]
            params = call_args[1]["params"]
            assert "/3/search/multi" in url
            assert params["query"] == "沙丘"
            assert params["language"] == "zh-CN"
            assert params["api_key"] == "test_key"
            assert params["page"] == 1

    def test_returns_parsed_json(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "page": 1,
                "results": [{"id": 693134, "title": "沙丘2"}],
                "total_pages": 1,
                "total_results": 1,
            }
            mock_response.raise_for_status.return_value = None
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            result = adapter.search_multi("沙丘")
            assert result["page"] == 1
            assert len(result["results"]) == 1
            assert result["results"][0]["title"] == "沙丘2"

    def test_http_error_raises_tmdb_error(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = Exception("HTTP 500")
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            with pytest.raises(TMDBError, match="TMDB API error"):
                adapter.search_multi("query")


class TestTMDBAdapterMovieDetails:
    def test_appends_external_ids(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": 693134,
                "title": "沙丘2",
                "external_ids": {"imdb_id": "tt15239678"},
            }
            mock_response.raise_for_status.return_value = None
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            adapter.movie_details(693134)

            params = mock_client.get.call_args[1]["params"]
            assert "append_to_response" in params
            assert "external_ids" in params["append_to_response"]

    def test_always_includes_language_zh_cn(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"id": 693134}
            mock_response.raise_for_status.return_value = None
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            adapter.movie_details(693134)

            params = mock_client.get.call_args[1]["params"]
            assert params["language"] == "zh-CN"


class TestTMDBAdapterTvDetails:
    def test_appends_external_ids(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": 1399,
                "name": "权力的游戏",
                "external_ids": {"imdb_id": "tt0944947"},
            }
            mock_response.raise_for_status.return_value = None
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            adapter.tv_details(1399)

            params = mock_client.get.call_args[1]["params"]
            assert "append_to_response" in params
            assert "external_ids" in params["append_to_response"]


class TestTMDBAdapterDiscover:
    def test_discover_movie_passes_filters(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"page": 1, "results": []}
            mock_response.raise_for_status.return_value = None
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            adapter.discover_movie(
                sort_by="vote_average.desc",
                with_genres="878",
                primary_release_year=2024,
                vote_count_gte=200,
            )

            params = mock_client.get.call_args[1]["params"]
            assert params["language"] == "zh-CN"
            assert params["sort_by"] == "vote_average.desc"
            assert params["with_genres"] == "878"
            assert params["primary_release_year"] == 2024
            assert params["vote_count_gte"] == 200

    def test_discover_tv_passes_filters(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"page": 1, "results": []}
            mock_response.raise_for_status.return_value = None
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            adapter.discover_tv(
                sort_by="popularity.desc",
                first_air_date_year=2024,
            )

            params = mock_client.get.call_args[1]["params"]
            assert params["language"] == "zh-CN"
            assert params["sort_by"] == "popularity.desc"
            assert params["first_air_date_year"] == 2024


class TestTMDBAdapterTrending:
    def test_trending_all_uses_day_default(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"page": 1, "results": []}
            mock_response.raise_for_status.return_value = None
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            adapter.trending_all("week")

            url = mock_client.get.call_args[0][0]
            params = mock_client.get.call_args[1]["params"]
            assert "/3/trending/all/week" in url
            assert params["language"] == "zh-CN"


class TestTMDBAdapterHealth:
    def test_health_returns_true_on_success(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"success": True}
            mock_response.raise_for_status.return_value = None
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            result = adapter.health()
            assert result is True

            url = mock_client.get.call_args[0][0]
            assert "/3/authentication" in url

    def test_health_returns_false_on_error(self):
        adapter = TMDBAdapter(api_key="test_key")
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = Exception("Network error")
            mock_client.__enter__.return_value = mock_client
            mock_client_cls.return_value = mock_client

            result = adapter.health()
            assert result is False
```

- [ ] **Step 2: 运行测试验证失败**

```bash
.venv/bin/python -m pytest tests/test_tmdb_adapter.py -v
```

预期：全部 FAIL（模块/类尚未创建）。

- [ ] **Step 3: 创建 `app/adapters/tmdb.py`**

```python
"""TMDB (The Movie Database) API v3 adapter.

Thin HTTP boundary for TMDB read-only endpoints. All requests
automatically attach language=zh-CN for Chinese responses.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TMDBError(Exception):
    """TMDB API 调用失败。"""


@dataclass(slots=True)
class TMDBAdapter:
    """TMDB API v3 适配器。

    Attributes:
        api_key: TMDB API v3 key（作为 api_key 查询参数发送）。
        base_url: TMDB API 基础 URL，默认 https://api.themoviedb.org。
        timeout_seconds: HTTP 请求超时（秒）。
    """

    api_key: str
    base_url: str = "https://api.themoviedb.org"
    timeout_seconds: float = 10.0

    def _is_configured(self) -> bool:
        return bool(self.api_key.strip())

    def _get(
        self,
        path: str,
        *,
        extra_params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """发送 GET 请求，自动附加 language=zh-CN 和 api_key。

        Raises:
            TMDBError: 当 HTTP 请求失败或 JSON 解析失败时。
        """
        base = self.base_url.rstrip("/")
        url = f"{base}{path}"
        params: dict[str, Any] = {
            "api_key": self.api_key,
            "language": "zh-CN",
        }
        if extra_params:
            params.update(extra_params)

        logger.debug("TMDB GET %s params=%s", url, {k: v for k, v in params.items() if k != "api_key"})
        try:
            with httpx.Client(timeout=timeout or self.timeout_seconds) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                parsed = response.json()
                if not isinstance(parsed, dict):
                    raise TMDBError("TMDB API returned non-object JSON")
                return parsed
        except httpx.HTTPError as exc:
            raise TMDBError(f"TMDB API error: {exc}") from exc

    # ── Search ──────────────────────────────────────────

    def search_multi(
        self,
        query: str,
        *,
        page: int = 1,
        include_adult: bool = False,
    ) -> dict[str, Any]:
        """GET /3/search/multi — 统一搜索电影、电视剧和人物。

        Args:
            query: 搜索关键词。
            page: 页码。
            include_adult: 是否包含成人内容。

        Returns:
            API 返回的 JSON 对象。
        """
        if not self._is_configured():
            logger.warning("TMDB search_multi skipped: adapter is not configured")
            return {"page": 1, "results": [], "total_pages": 1, "total_results": 0}
        logger.info("TMDB search_multi query=%s page=%s", query, page)
        return self._get(
            "/3/search/multi",
            extra_params={
                "query": query,
                "page": page,
                "include_adult": "true" if include_adult else "false",
            },
        )

    # ── Details ─────────────────────────────────────────

    def movie_details(self, movie_id: int) -> dict[str, Any]:
        """GET /3/movie/{id} — 获取电影详情，自动附加 external_ids。

        Args:
            movie_id: TMDB 电影 ID。
        """
        if not self._is_configured():
            logger.warning("TMDB movie_details skipped: adapter is not configured")
            return {}
        logger.info("TMDB movie_details id=%s", movie_id)
        return self._get(
            f"/3/movie/{movie_id}",
            extra_params={"append_to_response": "external_ids"},
        )

    def tv_details(self, series_id: int) -> dict[str, Any]:
        """GET /3/tv/{id} — 获取电视剧详情，自动附加 external_ids。

        Args:
            series_id: TMDB 电视剧 ID。
        """
        if not self._is_configured():
            logger.warning("TMDB tv_details skipped: adapter is not configured")
            return {}
        logger.info("TMDB tv_details id=%s", series_id)
        return self._get(
            f"/3/tv/{series_id}",
            extra_params={"append_to_response": "external_ids"},
        )

    # ── Discover ────────────────────────────────────────

    def discover_movie(self, **filters: Any) -> dict[str, Any]:
        """GET /3/discover/movie — 按条件发现电影。

        支持的过滤器：
            sort_by, with_genres, with_origin_country,
            primary_release_year, primary_release_date_gte, primary_release_date_lte,
            vote_average_gte, vote_average_lte, vote_count_gte, vote_count_lte,
            with_people, with_keywords, with_companies,
            region, year, page, include_adult, include_video.
        """
        if not self._is_configured():
            logger.warning("TMDB discover_movie skipped: adapter is not configured")
            return {"page": 1, "results": [], "total_pages": 1, "total_results": 0}
        logger.info("TMDB discover_movie filters=%s", dict(filters))
        return self._get(
            "/3/discover/movie",
            extra_params={k: v for k, v in filters.items() if v is not None},
        )

    def discover_tv(self, **filters: Any) -> dict[str, Any]:
        """GET /3/discover/tv — 按条件发现电视剧。

        支持的过滤器：
            sort_by, with_genres, with_origin_country,
            first_air_date_year, first_air_date_gte, first_air_date_lte,
            vote_average_gte, vote_average_lte, vote_count_gte, vote_count_lte,
            with_people, with_keywords, with_networks,
            region, page, include_adult.
        """
        if not self._is_configured():
            logger.warning("TMDB discover_tv skipped: adapter is not configured")
            return {"page": 1, "results": [], "total_pages": 1, "total_results": 0}
        logger.info("TMDB discover_tv filters=%s", dict(filters))
        return self._get(
            "/3/discover/tv",
            extra_params={k: v for k, v in filters.items() if v is not None},
        )

    # ── Trending ────────────────────────────────────────

    def trending_all(
        self,
        time_window: str = "day",
    ) -> dict[str, Any]:
        """GET /3/trending/all/{time_window} — 获取热门趋势。

        Args:
            time_window: 时间窗口，"day" 或 "week"。
        """
        if not self._is_configured():
            logger.warning("TMDB trending_all skipped: adapter is not configured")
            return {"page": 1, "results": [], "total_pages": 1, "total_results": 0}
        logger.info("TMDB trending_all time_window=%s", time_window)
        return self._get(f"/3/trending/all/{time_window}")

    # ── Health ──────────────────────────────────────────

    def health(self) -> bool:
        """GET /3/authentication — 验证 API 连通性。

        Returns:
            True 当 API 连接正常，False 当请求失败。
        """
        try:
            self._get("/3/authentication", timeout=5.0)
            return True
        except TMDBError:
            logger.warning("TMDB health check failed")
            return False
```

- [ ] **Step 4: 运行测试验证通过**

```bash
.venv/bin/python -m pytest tests/test_tmdb_adapter.py -v
```

预期：全部 PASS。

- [ ] **Step 5: 验证编译**

```bash
.venv/bin/python -m compileall app/adapters/tmdb.py -q
```

- [ ] **Step 6: Commit**

```bash
git add app/adapters/tmdb.py tests/test_tmdb_adapter.py
git commit -m "feat: add TMDBAdapter with search/details/discover/trending/health methods

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: tmdb_search 工具 + 测试

**Files:**
- Create: `app/tools/tmdb_search.py`
- Create: `tests/test_tmdb_tools.py`（含 tmdb_search 测试）

- [ ] **Step 1: 创建 `tests/test_tmdb_tools.py` 并写入 tmdb_search 测试**

```python
"""Tests for TMDB tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.tools.tmdb_search import TMDBSearchTool
from hello_agents.tools.response import ToolResponse


class TestTMDBSearchTool:
    def test_requires_query_parameter(self):
        """query 是必填参数。"""
        tool = TMDBSearchTool(MagicMock())
        params = tool.get_parameters()
        query_param = next(p for p in params if p.name == "query")
        assert query_param.required is True

    def test_media_type_optional(self):
        """media_type 是可选参数。"""
        tool = TMDBSearchTool(MagicMock())
        params = tool.get_parameters()
        media_param = next(p for p in params if p.name == "media_type")
        assert media_param.required is False

    def test_media_type_has_enum(self):
        """media_type 枚举值正确。"""
        tool = TMDBSearchTool(MagicMock())
        params = tool.get_parameters()
        media_param = next(p for p in params if p.name == "media_type")
        assert set(media_param.enum) == {"movie", "tv", "person"}

    def test_run_calls_adapter_and_returns_results(self):
        mock_adapter = MagicMock()
        mock_adapter.search_multi.return_value = {
            "page": 1,
            "results": [
                {
                    "id": 693134,
                    "title": "沙丘2",
                    "media_type": "movie",
                    "overview": "保罗·厄崔迪的传奇故事继续上演。",
                    "release_date": "2024-03-01",
                    "popularity": 100.5,
                    "vote_average": 8.2,
                    "vote_count": 3000,
                },
                {
                    "id": 1399,
                    "name": "权力的游戏",
                    "media_type": "tv",
                    "overview": "维斯特洛大陆的权力斗争。",
                    "first_air_date": "2011-04-17",
                    "popularity": 200.3,
                    "vote_average": 8.5,
                    "vote_count": 15000,
                },
            ],
            "total_results": 2,
        }
        tool = TMDBSearchTool(mock_adapter)

        response = tool.run({"query": "沙丘"})

        mock_adapter.search_multi.assert_called_once_with("沙丘")
        assert response.status.value == "success"
        candidates = response.data["candidates"]
        assert len(candidates) == 2
        assert candidates[0]["tmdb_id"] == 693134
        assert candidates[0]["title"] == "沙丘2"
        assert candidates[0]["media_type"] == "movie"

    def test_filters_by_media_type(self):
        """media_type 筛选正确过滤结果。"""
        mock_adapter = MagicMock()
        mock_adapter.search_multi.return_value = {
            "page": 1,
            "results": [
                {"id": 1, "title": "Movie A", "media_type": "movie"},
                {"id": 2, "name": "TV Show A", "media_type": "tv"},
                {"id": 3, "title": "Movie B", "media_type": "movie"},
            ],
            "total_results": 3,
        }
        tool = TMDBSearchTool(mock_adapter)

        response = tool.run({"query": "test", "media_type": "movie"})

        candidates = response.data["candidates"]
        assert len(candidates) == 2
        assert all(c["media_type"] == "movie" for c in candidates)

    def test_limits_results_to_5(self):
        """最多返回 5 条结果。"""
        mock_adapter = MagicMock()
        mock_adapter.search_multi.return_value = {
            "page": 1,
            "results": [
                {"id": i, "title": f"Movie {i}", "media_type": "movie"}
                for i in range(10)
            ],
            "total_results": 10,
        }
        tool = TMDBSearchTool(mock_adapter)

        response = tool.run({"query": "test"})

        assert len(response.data["candidates"]) == 5

    def test_handles_empty_query(self):
        """空关键词返回错误。"""
        mock_adapter = MagicMock()
        tool = TMDBSearchTool(mock_adapter)

        response = tool.run({"query": ""})

        assert response.status.value == "error"
        assert "keyword" in response.text.lower()

    def test_handles_adapter_error(self):
        """adapter 异常时返回错误响应。"""
        mock_adapter = MagicMock()
        mock_adapter.search_multi.side_effect = Exception("Network error")
        tool = TMDBSearchTool(mock_adapter)

        response = tool.run({"query": "test"})

        assert response.status.value == "error"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
.venv/bin/python -m pytest tests/test_tmdb_tools.py::TestTMDBSearchTool -v
```

预期：全部 FAIL。

- [ ] **Step 3: 创建 `app/tools/tmdb_search.py`**

```python
"""TMDBSearchTool — 搜索 TMDB 影视数据库。"""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.tmdb import TMDBAdapter, TMDBError


class TMDBSearchTool(Tool):
    """搜索 TMDB 电影、电视剧和人物。"""

    _MEDIA_TYPES = ["movie", "tv", "person"]
    _RESULT_LIMIT = 5

    def __init__(self, adapter: TMDBAdapter) -> None:
        super().__init__(
            name="tmdb_search",
            description=(
                "搜索 TMDB 影视数据库（电影/电视剧/人物）。返回中文标题、媒体类型、"
                "TMDB ID 和概述。可用 media_type 筛选类型，或省略以查看全部。"
                "当用户提到的片名存在歧义时（如'星球大战'可能指多部电影或动画），"
                "结果会展示多种可能，便于向用户澄清后精确搜索。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="搜索关键词（中英文均可）。",
                required=True,
            ),
            ToolParameter(
                name="media_type",
                type="string",
                description="筛选媒体类型。用户明确要求电影/电视剧/人物时使用；省略则返回全部类型。",
                required=False,
                enum=self._MEDIA_TYPES,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        query = str(parameters.get("query", "")).strip()
        if not query:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="搜索关键词（query）不能为空。",
            )
        if len(query) > 200:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="搜索关键词不能超过 200 个字符。",
            )

        media_type = str(parameters.get("media_type") or "").strip().lower() or None
        if media_type is not None and media_type not in self._MEDIA_TYPES:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=f"media_type 必须是: {', '.join(self._MEDIA_TYPES)}。",
            )

        try:
            raw = self._adapter.search_multi(query)
        except TMDBError as exc:
            return ToolResponse.error(
                code="TMDB_ERROR",
                message=f"TMDB 搜索失败: {exc}",
            )

        all_results: list[dict[str, Any]] = raw.get("results", [])
        if media_type:
            all_results = [
                r for r in all_results
                if r.get("media_type") == media_type
            ]

        candidates: list[dict[str, Any]] = []
        for item in all_results[: self._RESULT_LIMIT]:
            media_type_value = item.get("media_type", "unknown")
            is_movie = media_type_value == "movie"
            candidates.append({
                "tmdb_id": item.get("id"),
                "title": item.get("title") if is_movie else item.get("name", ""),
                "original_title": item.get("original_title") if is_movie else item.get("original_name", ""),
                "media_type": media_type_value,
                "overview": item.get("overview", ""),
                "release_date": item.get("release_date") if is_movie else item.get("first_air_date"),
                "popularity": item.get("popularity"),
                "vote_average": item.get("vote_average"),
                "vote_count": item.get("vote_count"),
            })

        return ToolResponse.success(
            text=(
                f"找到 {len(candidates)} 条 TMDB 搜索结果"
                f"（总共 {raw.get('total_results', 0)} 条匹配）"
                + (f"，已筛选 media_type={media_type}" if media_type else "")
                + "。"
            ),
            data={
                "query": query,
                "media_type": media_type,
                "total_results": raw.get("total_results", 0),
                "returned_count": len(candidates),
                "candidates": candidates,
            },
        )
```

- [ ] **Step 4: 运行测试验证通过**

```bash
.venv/bin/python -m pytest tests/test_tmdb_tools.py::TestTMDBSearchTool -v
```

预期：全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/tools/tmdb_search.py tests/test_tmdb_tools.py
git commit -m "feat: add tmdb_search tool

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: tmdb_details 工具 + 测试

**Files:**
- Create: `app/tools/tmdb_details.py`
- Modify: `tests/test_tmdb_tools.py`（追加 tmdb_details 测试）

- [ ] **Step 1: 追加 tmdb_details 测试到 `tests/test_tmdb_tools.py`**

在文件末尾追加：

```python
class TestTMDBDetailsTool:
    def test_requires_tmdb_id_and_media_type(self):
        tool = TMDBDetailsTool(MagicMock())
        params = {p.name: p for p in tool.get_parameters()}
        assert params["tmdb_id"].required is True
        assert params["media_type"].required is True
        assert set(params["media_type"].enum) == {"movie", "tv"}

    def test_run_movie_details(self):
        mock_adapter = MagicMock()
        mock_adapter.movie_details.return_value = {
            "id": 693134,
            "title": "沙丘2",
            "original_title": "Dune: Part Two",
            "overview": "保罗·厄崔迪的传奇故事继续上演。",
            "release_date": "2024-03-01",
            "runtime": 166,
            "genres": [
                {"id": 878, "name": "科幻"},
                {"id": 12, "name": "冒险"},
            ],
            "vote_average": 8.2,
            "vote_count": 3500,
            "external_ids": {
                "imdb_id": "tt15239678",
            },
        }
        tool = TMDBDetailsTool(mock_adapter)

        response = tool.run({"tmdb_id": 693134, "media_type": "movie"})

        mock_adapter.movie_details.assert_called_once_with(693134)
        assert response.status.value == "success"
        detail = response.data["detail"]
        assert detail["title"] == "沙丘2"
        assert detail["imdb_id"] == "tt15239678"
        assert detail["media_type"] == "movie"
        assert len(detail["genres"]) == 2

    def test_run_tv_details(self):
        mock_adapter = MagicMock()
        mock_adapter.tv_details.return_value = {
            "id": 1399,
            "name": "权力的游戏",
            "original_name": "Game of Thrones",
            "overview": "维斯特洛大陆的权力斗争。",
            "first_air_date": "2011-04-17",
            "number_of_seasons": 8,
            "number_of_episodes": 73,
            "genres": [
                {"id": 10765, "name": "Sci-Fi & Fantasy"},
                {"id": 18, "name": "剧情"},
            ],
            "vote_average": 8.5,
            "vote_count": 15000,
            "external_ids": {
                "imdb_id": "tt0944947",
            },
        }
        tool = TMDBDetailsTool(mock_adapter)

        response = tool.run({"tmdb_id": 1399, "media_type": "tv"})

        mock_adapter.tv_details.assert_called_once_with(1399)
        detail = response.data["detail"]
        assert detail["title"] == "权力的游戏"
        assert detail["imdb_id"] == "tt0944947"
        assert detail["media_type"] == "tv"
        assert detail["seasons"] == 8

    def test_rejects_invalid_media_type(self):
        tool = TMDBDetailsTool(MagicMock())
        response = tool.run({"tmdb_id": 123, "media_type": "person"})
        assert response.status.value == "error"

    def test_handles_adapter_error(self):
        mock_adapter = MagicMock()
        mock_adapter.movie_details.side_effect = Exception("Boom")
        tool = TMDBDetailsTool(mock_adapter)

        response = tool.run({"tmdb_id": 999, "media_type": "movie"})

        assert response.status.value == "error"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
.venv/bin/python -m pytest tests/test_tmdb_tools.py::TestTMDBDetailsTool -v
```

预期：全部 FAIL（类尚未创建）。

- [ ] **Step 3: 创建 `app/tools/tmdb_details.py`**

```python
"""TMDBDetailsTool — 获取 TMDB 影视详情。"""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.tmdb import TMDBAdapter, TMDBError


class TMDBDetailsTool(Tool):
    """获取电影或电视剧的详细信息，包括中文名称、概述、评分、类型和 IMDb ID。"""

    _MEDIA_TYPES = ["movie", "tv"]

    def __init__(self, adapter: TMDBAdapter) -> None:
        super().__init__(
            name="tmdb_details",
            description=(
                "获取 TMDB 影视作品详情：中文标题、概述、上映/首播日期、"
                "评分、类型、时长/季数，以及 IMDb ID（可用于 mteam_search 精准搜索）。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="tmdb_id",
                type="integer",
                description="TMDB 媒体 ID（来自 tmdb_search 或 tmdb_discover 结果）。",
                required=True,
            ),
            ToolParameter(
                name="media_type",
                type="string",
                description="媒体类型：movie（电影）或 tv（电视剧）。",
                required=True,
                enum=self._MEDIA_TYPES,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            tmdb_id = int(parameters.get("tmdb_id", 0))
        except (TypeError, ValueError):
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="tmdb_id 必须是有效的整数。",
            )
        if tmdb_id <= 0:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="tmdb_id 必须大于 0。",
            )

        media_type = str(parameters.get("media_type", "")).strip().lower()
        if media_type not in self._MEDIA_TYPES:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=f"media_type 必须是: {', '.join(self._MEDIA_TYPES)}。",
            )

        try:
            if media_type == "movie":
                raw = self._adapter.movie_details(tmdb_id)
            else:
                raw = self._adapter.tv_details(tmdb_id)
        except TMDBError as exc:
            return ToolResponse.error(
                code="TMDB_ERROR",
                message=f"TMDB 详情查询失败: {exc}",
            )

        if not raw:
            return ToolResponse.error(
                code="NOT_FOUND",
                message=f"TMDB {media_type} id={tmdb_id} 未找到。",
            )

        external_ids = raw.get("external_ids") or {}
        genres = [
            {"id": g["id"], "name": g["name"]}
            for g in raw.get("genres") or []
        ]

        is_movie = media_type == "movie"
        detail = {
            "tmdb_id": raw.get("id"),
            "title": raw.get("title") if is_movie else raw.get("name", ""),
            "original_title": raw.get("original_title") if is_movie else raw.get("original_name", ""),
            "media_type": media_type,
            "overview": raw.get("overview", ""),
            "release_date": raw.get("release_date") if is_movie else raw.get("first_air_date"),
            "genres": genres,
            "vote_average": raw.get("vote_average"),
            "vote_count": raw.get("vote_count"),
            "imdb_id": external_ids.get("imdb_id"),
            "popularity": raw.get("popularity"),
        }

        if is_movie:
            detail["runtime"] = raw.get("runtime")
        else:
            detail["seasons"] = raw.get("number_of_seasons")
            detail["episodes"] = raw.get("number_of_episodes")

        return ToolResponse.success(
            text=(
                f"{detail['title']} ({detail['original_title']}) — "
                f"{'电影' if is_movie else '电视剧'}，"
                + (f"{detail['runtime']} 分钟" if is_movie else f"{detail['seasons']} 季 {detail['episodes']} 集")
                + f"，评分 {detail['vote_average']}/10 ({detail['vote_count']} 票)"
                + (f"，IMDb: {detail['imdb_id']}" if detail.get('imdb_id') else "")
            ),
            data={"detail": detail},
        )
```

- [ ] **Step 4: 运行测试验证通过**

```bash
.venv/bin/python -m pytest tests/test_tmdb_tools.py::TestTMDBDetailsTool -v
```

预期：全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/tools/tmdb_details.py tests/test_tmdb_tools.py
git commit -m "feat: add tmdb_details tool

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: tmdb_discover 工具 + 测试

**Files:**
- Create: `app/tools/tmdb_discover.py`
- Modify: `tests/test_tmdb_tools.py`（追加 tmdb_discover 测试）

- [ ] **Step 1: 追加 tmdb_discover 测试到 `tests/test_tmdb_tools.py`**

在文件末尾追加：

```python
class TestTMDBDiscoverTool:
    def test_requires_media_type(self):
        tool = TMDBDiscoverTool(MagicMock())
        params = {p.name: p for p in tool.get_parameters()}
        assert params["media_type"].required is True
        assert set(params["media_type"].enum) == {"movie", "tv"}

    def test_optional_filters_have_defaults(self):
        tool = TMDBDiscoverTool(MagicMock())
        params = {p.name: p for p in tool.get_parameters()}
        for name in ("sort_by", "with_genres", "year", "vote_average_gte", "vote_count_gte"):
            assert params[name].required is False, f"{name} should be optional"

    def test_run_discover_movie_uses_correct_adapter_method(self):
        mock_adapter = MagicMock()
        mock_adapter.discover_movie.return_value = {
            "page": 1,
            "results": [
                {
                    "id": 693134,
                    "title": "沙丘2",
                    "overview": "...",
                    "release_date": "2024-03-01",
                    "vote_average": 8.2,
                    "vote_count": 3500,
                    "poster_path": "/abc.jpg",
                },
            ],
            "total_results": 1,
        }
        tool = TMDBDiscoverTool(mock_adapter)

        response = tool.run({
            "media_type": "movie",
            "sort_by": "vote_average.desc",
            "with_genres": "878",
            "year": 2024,
            "vote_count_gte": 200,
        })

        mock_adapter.discover_movie.assert_called_once()
        call_kwargs = mock_adapter.discover_movie.call_args[1]
        assert call_kwargs["sort_by"] == "vote_average.desc"
        assert call_kwargs["with_genres"] == "878"
        assert call_kwargs["primary_release_year"] == 2024
        assert call_kwargs["vote_count_gte"] == 200
        mock_adapter.discover_tv.assert_not_called()

    def test_run_discover_tv_uses_correct_adapter_method(self):
        mock_adapter = MagicMock()
        mock_adapter.discover_tv.return_value = {
            "page": 1,
            "results": [
                {
                    "id": 1399,
                    "name": "权力的游戏",
                    "overview": "...",
                    "first_air_date": "2011-04-17",
                    "vote_average": 8.5,
                    "vote_count": 15000,
                },
            ],
            "total_results": 1,
        }
        tool = TMDBDiscoverTool(mock_adapter)

        response = tool.run({
            "media_type": "tv",
            "sort_by": "popularity.desc",
            "year": 2011,
        })

        mock_adapter.discover_tv.assert_called_once()
        call_kwargs = mock_adapter.discover_tv.call_args[1]
        assert call_kwargs["first_air_date_year"] == 2011
        mock_adapter.discover_movie.assert_not_called()

    def test_limits_results_to_5(self):
        mock_adapter = MagicMock()
        mock_adapter.discover_movie.return_value = {
            "page": 1,
            "results": [
                {"id": i, "title": f"Movie {i}"} for i in range(10)
            ],
            "total_results": 10,
        }
        tool = TMDBDiscoverTool(mock_adapter)

        response = tool.run({"media_type": "movie"})

        assert len(response.data["candidates"]) == 5

    def test_handles_adapter_error(self):
        mock_adapter = MagicMock()
        mock_adapter.discover_movie.side_effect = Exception("Fail")
        tool = TMDBDiscoverTool(mock_adapter)

        response = tool.run({"media_type": "movie"})

        assert response.status.value == "error"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
.venv/bin/python -m pytest tests/test_tmdb_tools.py::TestTMDBDiscoverTool -v
```

预期：全部 FAIL。

- [ ] **Step 3: 创建 `app/tools/tmdb_discover.py`**

```python
"""TMDBDiscoverTool — 按条件发现 TMDB 影视作品。"""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.tmdb import TMDBAdapter, TMDBError


class TMDBDiscoverTool(Tool):
    """按类型、评分、年份等条件发现影视作品。"""

    _MEDIA_TYPES = ["movie", "tv"]
    _MOVIE_SORTS = [
        "popularity.asc", "popularity.desc",
        "vote_average.asc", "vote_average.desc",
        "release_date.asc", "release_date.desc",
        "revenue.asc", "revenue.desc",
    ]
    _TV_SORTS = [
        "popularity.asc", "popularity.desc",
        "vote_average.asc", "vote_average.desc",
        "first_air_date.asc", "first_air_date.desc",
    ]
    _RESULT_LIMIT = 5

    def __init__(self, adapter: TMDBAdapter) -> None:
        super().__init__(
            name="tmdb_discover",
            description=(
                "按条件发现 TMDB 影视作品。可按类型（电影/电视剧）、评分、"
                "年份、流派等筛选，按人气、评分或日期排序。"
                "适合用户要求推荐或浏览某一类别影视时使用。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="media_type",
                type="string",
                description="媒体类型：movie（电影）或 tv（电视剧）。",
                required=True,
                enum=self._MEDIA_TYPES,
            ),
            ToolParameter(
                name="sort_by",
                type="string",
                description=(
                    "排序方式。movie 默认 popularity.desc，可选 vote_average.desc、"
                    "release_date.desc。tv 默认 popularity.desc。"
                ),
                required=False,
            ),
            ToolParameter(
                name="with_genres",
                type="string",
                description="TMDB 类型 ID，逗号分隔。例如科幻=878，动作=28。",
                required=False,
            ),
            ToolParameter(
                name="year",
                type="integer",
                description="年份过滤（电影为上映年份，电视剧为首播年份）。",
                required=False,
            ),
            ToolParameter(
                name="vote_average_gte",
                type="number",
                description="最低评分过滤（0-10）。",
                required=False,
            ),
            ToolParameter(
                name="vote_count_gte",
                type="integer",
                description="最低评分人数过滤（排除小众作品）。",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        media_type = str(parameters.get("media_type", "")).strip().lower()
        if media_type not in self._MEDIA_TYPES:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=f"media_type 必须是: {', '.join(self._MEDIA_TYPES)}。",
            )

        is_movie = media_type == "movie"

        # Build filter kwargs
        filters: dict[str, Any] = {}

        sort_by = str(parameters.get("sort_by") or "").strip() or None
        if sort_by:
            filters["sort_by"] = sort_by

        with_genres = str(parameters.get("with_genres") or "").strip() or None
        if with_genres:
            filters["with_genres"] = with_genres

        year = None
        try:
            year_raw = parameters.get("year")
            if year_raw is not None:
                year = int(year_raw)
        except (TypeError, ValueError):
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="year 必须是有效的整数。",
            )
        if year is not None:
            if is_movie:
                filters["primary_release_year"] = year
            else:
                filters["first_air_date_year"] = year

        vote_average_gte = None
        try:
            vote_avg_raw = parameters.get("vote_average_gte")
            if vote_avg_raw is not None:
                vote_average_gte = float(vote_avg_raw)
        except (TypeError, ValueError):
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="vote_average_gte 必须是有效的数字。",
            )
        if vote_average_gte is not None:
            filters["vote_average_gte"] = vote_average_gte

        vote_count_gte = None
        try:
            vote_cnt_raw = parameters.get("vote_count_gte")
            if vote_cnt_raw is not None:
                vote_count_gte = int(vote_cnt_raw)
        except (TypeError, ValueError):
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="vote_count_gte 必须是有效的整数。",
            )
        if vote_count_gte is not None:
            filters["vote_count_gte"] = vote_count_gte

        try:
            if is_movie:
                raw = self._adapter.discover_movie(**filters)
            else:
                raw = self._adapter.discover_tv(**filters)
        except TMDBError as exc:
            return ToolResponse.error(
                code="TMDB_ERROR",
                message=f"TMDB 发现查询失败: {exc}",
            )

        all_results: list[dict[str, Any]] = raw.get("results", [])
        candidates: list[dict[str, Any]] = []
        for item in all_results[: self._RESULT_LIMIT]:
            candidates.append({
                "tmdb_id": item.get("id"),
                "title": item.get("title") if is_movie else item.get("name", ""),
                "original_title": item.get("original_title") if is_movie else item.get("original_name", ""),
                "media_type": media_type,
                "overview": item.get("overview", ""),
                "release_date": item.get("release_date") if is_movie else item.get("first_air_date"),
                "vote_average": item.get("vote_average"),
                "vote_count": item.get("vote_count"),
                "popularity": item.get("popularity"),
            })

        return ToolResponse.success(
            text=(
                f"发现 {len(candidates)} 部{'电影' if is_movie else '电视剧'}"
                f"（总共 {raw.get('total_results', 0)} 部匹配）。"
            ),
            data={
                "media_type": media_type,
                "filters": filters,
                "total_results": raw.get("total_results", 0),
                "returned_count": len(candidates),
                "candidates": candidates,
            },
        )
```

- [ ] **Step 4: 运行测试验证通过**

```bash
.venv/bin/python -m pytest tests/test_tmdb_tools.py::TestTMDBDiscoverTool -v
```

预期：全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/tools/tmdb_discover.py tests/test_tmdb_tools.py
git commit -m "feat: add tmdb_discover tool

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: tmdb_trending 工具 + 测试

**Files:**
- Create: `app/tools/tmdb_trending.py`
- Modify: `tests/test_tmdb_tools.py`（追加 tmdb_trending 测试）

- [ ] **Step 1: 追加 tmdb_trending 测试到 `tests/test_tmdb_tools.py`**

在文件末尾追加：

```python
class TestTMDBTrendingTool:
    def test_optional_parameters(self):
        tool = TMDBTrendingTool(MagicMock())
        params = {p.name: p for p in tool.get_parameters()}
        assert params["media_type"].required is False
        assert params["time_window"].required is False
        assert set(params["media_type"].enum) == {"all", "movie", "tv", "person"}
        assert set(params["time_window"].enum) == {"day", "week"}

    def test_run_with_defaults(self):
        mock_adapter = MagicMock()
        mock_adapter.trending_all.return_value = {
            "page": 1,
            "results": [
                {
                    "id": 693134,
                    "title": "沙丘2",
                    "media_type": "movie",
                    "overview": "...",
                    "popularity": 100.5,
                    "vote_average": 8.2,
                },
            ],
            "total_results": 20,
        }
        tool = TMDBTrendingTool(mock_adapter)

        response = tool.run({})

        mock_adapter.trending_all.assert_called_once_with("day")
        assert response.status.value == "success"
        candidates = response.data["candidates"]
        assert len(candidates) == 1
        assert candidates[0]["tmdb_id"] == 693134

    def test_filters_by_media_type(self):
        mock_adapter = MagicMock()
        mock_adapter.trending_all.return_value = {
            "page": 1,
            "results": [
                {"id": 1, "title": "Movie", "media_type": "movie"},
                {"id": 2, "name": "TV Show", "media_type": "tv"},
                {"id": 3, "title": "Another Movie", "media_type": "movie"},
            ],
            "total_results": 3,
        }
        tool = TMDBTrendingTool(mock_adapter)

        response = tool.run({"media_type": "tv"})

        candidates = response.data["candidates"]
        assert len(candidates) == 1
        assert candidates[0]["media_type"] == "tv"

    def test_limits_results_to_5(self):
        mock_adapter = MagicMock()
        mock_adapter.trending_all.return_value = {
            "page": 1,
            "results": [{"id": i, "media_type": "movie"} for i in range(10)],
            "total_results": 10,
        }
        tool = TMDBTrendingTool(mock_adapter)

        response = tool.run({})

        assert len(response.data["candidates"]) == 5

    def test_rejects_invalid_time_window(self):
        tool = TMDBTrendingTool(MagicMock())
        response = tool.run({"time_window": "month"})
        assert response.status.value == "error"

    def test_handles_adapter_error(self):
        mock_adapter = MagicMock()
        mock_adapter.trending_all.side_effect = Exception("Boom")
        tool = TMDBTrendingTool(mock_adapter)

        response = tool.run({})

        assert response.status.value == "error"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
.venv/bin/python -m pytest tests/test_tmdb_tools.py::TestTMDBTrendingTool -v
```

预期：全部 FAIL。

- [ ] **Step 3: 创建 `app/tools/tmdb_trending.py`**

```python
"""TMDBTrendingTool — 获取 TMDB 热门趋势。"""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.tmdb import TMDBAdapter, TMDBError


class TMDBTrendingTool(Tool):
    """获取 TMDB 当前热门电影、电视剧和人物趋势。"""

    _MEDIA_TYPES = ["all", "movie", "tv", "person"]
    _TIME_WINDOWS = ["day", "week"]
    _RESULT_LIMIT = 5

    def __init__(self, adapter: TMDBAdapter) -> None:
        super().__init__(
            name="tmdb_trending",
            description=(
                "查看 TMDB 当前热门趋势。可选 media_type 筛选电影/电视剧/人物"
                "（默认 all 返回全部），time_window 选择今日或本周趋势。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="media_type",
                type="string",
                description="筛选媒体类型。all（全部）/ movie（电影）/ tv（电视剧）/ person（人物）。默认为 all。",
                required=False,
                enum=self._MEDIA_TYPES,
            ),
            ToolParameter(
                name="time_window",
                type="string",
                description="时间窗口：day（今日）或 week（本周）。默认为 day。",
                required=False,
                enum=self._TIME_WINDOWS,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        media_type = str(parameters.get("media_type") or "all").strip().lower()
        time_window = str(parameters.get("time_window") or "day").strip().lower()

        if media_type not in self._MEDIA_TYPES:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=f"media_type 必须是: {', '.join(self._MEDIA_TYPES)}。",
            )
        if time_window not in self._TIME_WINDOWS:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=f"time_window 必须是: {', '.join(self._TIME_WINDOWS)}。",
            )

        try:
            raw = self._adapter.trending_all(time_window)
        except TMDBError as exc:
            return ToolResponse.error(
                code="TMDB_ERROR",
                message=f"TMDB 热门趋势查询失败: {exc}",
            )

        all_results: list[dict[str, Any]] = raw.get("results", [])
        if media_type != "all":
            all_results = [
                r for r in all_results
                if r.get("media_type") == media_type
            ]

        candidates: list[dict[str, Any]] = []
        for item in all_results[: self._RESULT_LIMIT]:
            item_media_type = item.get("media_type", "unknown")
            is_movie = item_media_type == "movie"
            candidates.append({
                "tmdb_id": item.get("id"),
                "title": item.get("title") if is_movie else item.get("name", ""),
                "original_title": item.get("original_title") if is_movie else item.get("original_name", ""),
                "media_type": item_media_type,
                "overview": item.get("overview", ""),
                "release_date": item.get("release_date") if is_movie else item.get("first_air_date"),
                "popularity": item.get("popularity"),
                "vote_average": item.get("vote_average"),
                "vote_count": item.get("vote_count"),
            })

        window_label = "今日" if time_window == "day" else "本周"
        type_label = {"all": "全部", "movie": "电影", "tv": "电视剧", "person": "人物"}[media_type]

        return ToolResponse.success(
            text=(
                f"{window_label}{type_label}热门趋势：{len(candidates)} 条结果"
                f"（总共 {raw.get('total_results', 0)} 条）。"
            ),
            data={
                "media_type": media_type,
                "time_window": time_window,
                "total_results": raw.get("total_results", 0),
                "returned_count": len(candidates),
                "candidates": candidates,
            },
        )
```

- [ ] **Step 4: 运行测试验证通过**

```bash
.venv/bin/python -m pytest tests/test_tmdb_tools.py::TestTMDBTrendingTool -v
```

预期：全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/tools/tmdb_trending.py tests/test_tmdb_tools.py
git commit -m "feat: add tmdb_trending tool

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: 注册工具 —— 更新 `__init__.py`、runner Filter 和 System Prompt

**Files:**
- Modify: `app/tools/__init__.py`
- Modify: `app/agent/runner.py`

- [ ] **Step 1: 更新 `app/tools/__init__.py` 导出 TMDB 工具**

将当前文件内容替换为：

```python
"""NasClawBot tool wrappers.

Each tool wraps an existing adapter operation behind the Tool protocol.
"""

from app.tools.member_profile import MemberProfileTool
from app.tools.mteam_search import MTeamSearchTool
from app.tools.qb_add_torrent import QBAddTorrentTool
from app.tools.qb_list_torrents import QBListTorrentsTool
from app.tools.qb_get_torrent import QBGetTorrentTool
from app.tools.qb_list_categories import QBListCategoriesTool
from app.tools.qb_control_torrent import QBControlTorrentTool
from app.tools.qb_set_global_speed import QBSetGlobalSpeedTool
from app.tools.qb_set_torrent_speed import QBSetTorrentSpeedTool
from app.tools.tmdb_search import TMDBSearchTool
from app.tools.tmdb_details import TMDBDetailsTool
from app.tools.tmdb_discover import TMDBDiscoverTool
from app.tools.tmdb_trending import TMDBTrendingTool

__all__ = [
    "MemberProfileTool",
    "MTeamSearchTool",
    "QBAddTorrentTool",
    "QBListTorrentsTool",
    "QBGetTorrentTool",
    "QBListCategoriesTool",
    "QBControlTorrentTool",
    "QBSetGlobalSpeedTool",
    "QBSetTorrentSpeedTool",
    "TMDBSearchTool",
    "TMDBDetailsTool",
    "TMDBDiscoverTool",
    "TMDBTrendingTool",
]
```

- [ ] **Step 2: 更新 `app/agent/runner.py` 导入 TMDB 工具**

在文件顶部 `from app.tools import (` 块中，追加 4 个新工具：

```python
from app.tools import (
    MemberProfileTool,
    MTeamSearchTool,
    QBAddTorrentTool,
    QBListTorrentsTool,
    QBGetTorrentTool,
    QBListCategoriesTool,
    QBControlTorrentTool,
    QBSetGlobalSpeedTool,
    QBSetTorrentSpeedTool,
    TMDBSearchTool,
    TMDBDetailsTool,
    TMDBDiscoverTool,
    TMDBTrendingTool,
)
```

同时新增 `from app.adapters.tmdb import TMDBAdapter` 导入。在现有 adapter 导入行附近添加：

```python
from app.adapters.tmdb import TMDBAdapter
```

- [ ] **Step 3: 更新 `runner.py` 中 `__init__` 的 Filter allow list**

找到 `self.tool_filter = tool_filter or Filter(allow=[` 段，在 `"qb_set_torrent_speed",` 之后追加：

```python
            "tmdb_search",
            "tmdb_details",
            "tmdb_discover",
            "tmdb_trending",
```

- [ ] **Step 4: 更新 `runner.py` 中 `_build_agent` 方法注册 TMDB 工具**

在 `_build_agent` 方法中，在现有 `registry.register_tool(QBSetTorrentSpeedTool(qb_adapter))` 之后，新增：

```python
        tmdb_adapter = TMDBAdapter(api_key=settings.tmdb_api_key)
        registry.register_tool(TMDBSearchTool(tmdb_adapter))
        registry.register_tool(TMDBDetailsTool(tmdb_adapter))
        registry.register_tool(TMDBDiscoverTool(tmdb_adapter))
        registry.register_tool(TMDBTrendingTool(tmdb_adapter))
```

- [ ] **Step 5: 更新 System Prompt — 在 `AGENT_SESSION_PROMPT` 中追加 TMDB 说明**

找到 `AGENT_SESSION_PROMPT` 中 "当已有信息足够时，直接回答。" 之前，插入：

```
你也可以搜索 TMDB 影视数据库来辅助查找资源：
- tmdb_search: 搜索电影/电视剧/人物，可按 media_type 筛选。当用户输入的片名存在歧义时（如"星球大战"可能指多部作品），结果会展示所有可能，此时应向用户追问澄清具体是哪一部。
- tmdb_details: 获取影视详情（标题、概述、评分、类型、IMDb ID 等）。IMDb ID 可用于后续 mteam_search 的 imdb 参数进行精准搜索。
- tmdb_discover: 按类型、评分、年份等条件发现影视作品。适合用户要求推荐或浏览某一类别时使用。
- tmdb_trending: 查看当前热门电影/电视剧/人物趋势（今日或本周）。

使用 TMDB 工具找到准确的影视中文名称和 IMDb ID 后，用 mteam_search 的 imdb 参数精准搜索 M-Team 资源能获得更好的匹配结果。
这些工具均为只读，直接执行。
```

- [ ] **Step 6: 验证编译和现有测试**

```bash
.venv/bin/python -m compileall app/tools app/agent -q
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_mcp
```

预期：所有现有测试 PASS，无编译错误。

- [ ] **Step 7: 验证 TMDB 适配器不属于 MCP（优雅降级不受影响）**

确认 `app/mcp_pool.py` 中没有引用 TMDB 相关代码 — TMDB 工具是原生 Tool，不经过 MCP bridge。

```bash
.venv/bin/python -m pytest tests/test_mcp/ -q
```

预期：MCP 相关测试 PASS（如有配置跳过则 SKIP）。

- [ ] **Step 8: Commit**

```bash
git add app/tools/__init__.py app/agent/runner.py
git commit -m "feat: register TMDB tools in runner, Filter, and system prompt

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: 最终验证 — 全量测试 + 编译

**Files:** 无新建，全量验证。

- [ ] **Step 1: 运行全量测试**

```bash
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_mcp
```

预期：全部 PASS（含新的 test_tmdb_adapter 和 test_tmdb_tools）。

- [ ] **Step 2: 验证全项目编译**

```bash
.venv/bin/python -m compileall app hello_agents -q
```

预期：无错误输出。

- [ ] **Step 3: 验证 TMDB adapter 在未配置时返回空（安全降级）**

```bash
.venv/bin/python -c "
from app.adapters.tmdb import TMDBAdapter
adapter = TMDBAdapter(api_key='')
result = adapter.search_multi('test')
assert result == {'page': 1, 'results': [], 'total_pages': 1, 'total_results': 0}
print('OK: unconfigured adapter returns empty results')
"
```

预期：`OK: unconfigured adapter returns empty results`。

- [ ] **Step 4: Commit（如有改动）**

```bash
git status
```

如果有未提交的改动，commit 它们。否则跳过。
```

---

## 自审

**1. Spec coverage check:**
- ✅ TMDBAdapter with all 6 methods (search_multi, movie_details, tv_details, discover_movie, discover_tv, trending_all) + health
- ✅ 4 tools: tmdb_search, tmdb_details, tmdb_discover, tmdb_trending
- ✅ language=zh-CN on all requests
- ✅ external_ids via append_to_response in details methods
- ✅ API key from Settings/env
- ✅ Filter allow list update
- ✅ System prompt update
- ✅ Gate not needed (all TMDB tools are read-only)
- ✅ 5 result limit on all tools
- ✅ Health check uses /3/authentication
- ✅ Error handling with TMDBError
- ✅ Disambiguation scenario covered in tool descriptions

**2. Placeholder scan:** No TBD, TODO, or vague instructions found.

**3. Type consistency:**
- TMDBAdapter methods use consistent naming: `search_multi`, `movie_details`, `tv_details`, `discover_movie`, `discover_tv`, `trending_all`, `health`
- Tool classes: `TMDBSearchTool`, `TMDBDetailsTool`, `TMDBDiscoverTool`, `TMDBTrendingTool`
- ToolResponse `data` keys: consistent `candidates` list with `tmdb_id`, `title`, `media_type`, `overview`, etc.
- Import paths match file paths

**4. Edge cases covered:**
- Empty API key → adapter returns empty results (graceful)
- Empty query → error response
- Invalid media_type → error response
- Adapter exception → error response
- >5 results → truncated to 5

**5. MCP check:** TMDB tools are native Tool implementations, not MCP — they do not use `McpBridgeTool` or the MCP pool. This is correct and intentional.
```

