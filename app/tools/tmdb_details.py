"""TMDBDetailsTool — fetch TMDB movie or TV show details."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.tmdb import TMDBAdapter, TMDBError


_VALID_MEDIA_TYPES = frozenset({"movie", "tv"})


class TMDBDetailsTool(Tool):
    """Fetch TMDB details for a movie or TV show (title, overview, IMDb ID, etc.)."""

    def __init__(self, adapter: TMDBAdapter) -> None:
        super().__init__(
            name="tmdb_details",
            description=(
                "获取已确定 TMDB movie/tv 条目的结构化详情：标题、原名、概述、"
                "上映/首播日期、评分、类型、时长/季数、季集信息和 IMDb ID。"
                "IMDb ID 仅作为辅助线索；电视剧、综艺、动画剧集资源仍优先用名称、年份、季号、集号搜索 M-Team。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="tmdb_id",
                type="integer",
                description="TMDB 媒体 ID",
                required=True,
            ),
            ToolParameter(
                name="media_type",
                type="string",
                description="媒体类型：movie（电影）或 tv（电视剧）",
                required=True,
                enum=list(_VALID_MEDIA_TYPES),
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            tmdb_id = self._validate_tmdb_id(parameters.get("tmdb_id"))
            media_type = self._validate_media_type(parameters.get("media_type"))
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        try:
            if media_type == "movie":
                raw = self._adapter.movie_details(tmdb_id)
            else:
                raw = self._adapter.tv_details(tmdb_id)
        except TMDBError as exc:
            return ToolResponse.error(
                code="TMDB_ERROR",
                message=f"TMDB 查询失败: {exc}",
            )
        except Exception as exc:
            return ToolResponse.error(
                code="INTERNAL_ERROR",
                message=f"查询时发生内部错误: {exc}",
            )

        if not raw or not raw.get("id"):
            return ToolResponse.error(
                code="NOT_FOUND",
                message=f"未找到 TMDB {media_type} (ID: {tmdb_id})。",
            )

        detail = self._normalize_detail(raw, media_type)
        return ToolResponse.success(
            text=(
                f"查询到 {detail['title']} 的详细信息，"
                f"IMDb ID: {detail.get('imdb_id', '无')}。"
            ),
            data={"detail": detail},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_tmdb_id(raw: Any) -> int:
        try:
            tmdb_id = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError("tmdb_id 必须是一个整数。") from None
        if tmdb_id <= 0:
            raise ValueError("tmdb_id 必须大于 0。")
        return tmdb_id

    @staticmethod
    def _validate_media_type(raw: Any) -> str:
        if not isinstance(raw, str) or raw not in _VALID_MEDIA_TYPES:
            raise ValueError("media_type 必须是 movie 或 tv。")
        return raw

    @staticmethod
    def _normalize_detail(raw: dict[str, Any], media_type: str) -> dict[str, Any]:
        external_ids = raw.get("external_ids") or {}
        detail: dict[str, Any] = {
            "tmdb_id": raw.get("id"),
            "media_type": media_type,
            "overview": raw.get("overview") or "",
            "vote_average": raw.get("vote_average"),
            "vote_count": raw.get("vote_count"),
            "popularity": raw.get("popularity"),
            "genres": raw.get("genres", []),
            "imdb_id": external_ids.get("imdb_id"),
        }

        if media_type == "movie":
            detail["title"] = raw.get("title") or "未知标题"
            detail["original_title"] = raw.get("original_title")
            detail["release_date"] = raw.get("release_date")
            detail["runtime"] = raw.get("runtime")
            # Expose collection info so library-audit can detect series gaps
            detail["belongs_to_collection"] = raw.get("belongs_to_collection")
        else:
            detail["title"] = raw.get("name") or "未知标题"
            detail["original_title"] = raw.get("original_name")
            detail["first_air_date"] = raw.get("first_air_date")
            detail["last_air_date"] = raw.get("last_air_date")
            detail["in_production"] = raw.get("in_production")
            detail["number_of_seasons"] = raw.get("number_of_seasons")
            detail["number_of_episodes"] = raw.get("number_of_episodes")
            # Per-season breakdown so the LLM can identify the latest season
            raw_seasons: list[dict[str, Any]] = raw.get("seasons") or []
            detail["seasons"] = [
                {
                    "season_number": s.get("season_number"),
                    "name": s.get("name"),
                    "episode_count": s.get("episode_count"),
                    "air_date": s.get("air_date"),
                }
                for s in raw_seasons
                if isinstance(s, dict) and s.get("season_number", 0) > 0
            ]
            # Latest / next episode summary
            last_ep = raw.get("last_episode_to_air")
            if isinstance(last_ep, dict):
                detail["last_episode_to_air"] = {
                    "season_number": last_ep.get("season_number"),
                    "episode_number": last_ep.get("episode_number"),
                    "name": last_ep.get("name"),
                    "air_date": last_ep.get("air_date"),
                }
            next_ep = raw.get("next_episode_to_air")
            if isinstance(next_ep, dict):
                detail["next_episode_to_air"] = {
                    "season_number": next_ep.get("season_number"),
                    "episode_number": next_ep.get("episode_number"),
                    "name": next_ep.get("name"),
                    "air_date": next_ep.get("air_date"),
                }

        return detail
