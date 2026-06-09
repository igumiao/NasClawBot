"""HTTP routes for M-Team free topped torrent browsing."""

from fastapi import APIRouter, Query

from app.adapters.mteam import MTeamAdapter
from app.api.schemas import FreeToppedResponse, FreeToppedTorrentSchema
from app.config import get_settings
from app.services.mteam_free_service import search_free_topped


def _build_mteam_adapter() -> MTeamAdapter:
    settings = get_settings()
    return MTeamAdapter(
        base_url=settings.mteam_base_url,
        api_key=settings.mteam_api_key,
    )


def build_mteam_router() -> APIRouter:
    router = APIRouter()

    @router.get("/mteam/free-topped", response_model=FreeToppedResponse)
    def get_free_topped(
        min_size_gb: float = Query(default=10.0, ge=0, description="Minimum size in GB"),
        topping_only: bool = Query(default=True, description="Only show topped torrents"),
    ) -> FreeToppedResponse:
        adapter = _build_mteam_adapter()
        result = search_free_topped(
            adapter=adapter,
            min_size_gb=min_size_gb,
            topping_only=topping_only,
        )
        return FreeToppedResponse(
            level2=[
                FreeToppedTorrentSchema(
                    id=t.id, name=t.name, size_bytes=t.size_bytes,
                    size_display=t.size_display, seeders=t.seeders,
                    leechers=t.leechers, discount=t.discount,
                    topping_level=t.topping_level, free_until=t.free_until,
                    category=t.category, imdb=t.imdb, douban=t.douban,
                )
                for t in result.level2_torrents
            ],
            level1=[
                FreeToppedTorrentSchema(
                    id=t.id, name=t.name, size_bytes=t.size_bytes,
                    size_display=t.size_display, seeders=t.seeders,
                    leechers=t.leechers, discount=t.discount,
                    topping_level=t.topping_level, free_until=t.free_until,
                    category=t.category, imdb=t.imdb, douban=t.douban,
                )
                for t in result.level1_torrents
            ],
            total_count=result.total_count,
        )

    return router
