"""Service for fetching and filtering free-topped M-Team torrents."""

from dataclasses import dataclass, field
from typing import Any

from app.adapters.mteam import MTeamAdapter

FREE_DISCOUNTS = {"FREE", "_2X_FREE", "_2X_PERCENT_50", "_2X"}


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    scale = 0
    value = float(size_bytes)
    while value >= 1024 and scale < len(units) - 1:
        value /= 1024
        scale += 1
    return f"{value:.2f} {units[scale]}"


def _gb_to_bytes(gb: float) -> int:
    return int(gb * 1024**3)


def _free_until(status: dict[str, Any]) -> str | None:
    """Return the effective free deadline: later of discountEndTime and mallSingleFree.endDate."""
    discount_end = str(status.get("discountEndTime") or "").strip() or None
    mall = status.get("mallSingleFree")
    mall_end = None
    if isinstance(mall, dict):
        mall_end = str(mall.get("endDate") or "").strip() or None
    # Return the later one (both are free), or whichever exists
    if discount_end and mall_end:
        return discount_end if discount_end > mall_end else mall_end
    return discount_end or mall_end


@dataclass
class FreeToppedTorrent:
    id: str
    name: str
    size_bytes: int
    size_display: str
    seeders: int
    leechers: int
    discount: str | None
    topping_level: int
    free_until: str | None
    category: str
    imdb: str | None
    douban: str | None
    team: str | None
    created_date: str | None


@dataclass
class FreeToppedResult:
    level2_torrents: list[FreeToppedTorrent] = field(default_factory=list)
    level1_torrents: list[FreeToppedTorrent] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.level2_torrents) + len(self.level1_torrents)


def _extract_candidate(item: dict[str, Any]) -> FreeToppedTorrent:
    status = item.get("status")
    if not isinstance(status, dict):
        status = {}
    size_bytes = _coerce_int(item.get("size"))
    return FreeToppedTorrent(
        id=str(item.get("id", "")).strip(),
        name=str(item.get("name", "")).strip(),
        size_bytes=size_bytes,
        size_display=_format_size(size_bytes),
        seeders=_coerce_int(status.get("seeders")),
        leechers=_coerce_int(status.get("leechers")),
        discount=str(status.get("discount") or "").strip() or None,
        topping_level=_coerce_int(status.get("toppingLevel", "0")),
        free_until=_free_until(status),
        category=str(item.get("category", "")).strip(),
        imdb=str(item.get("imdb") or "").strip() or None,
        douban=str(item.get("douban") or "").strip() or None,
        team=str(item.get("team") or "").strip() or None,
        created_date=str(item.get("createdDate", "")).strip() or None,
    )


def search_free_topped(
    adapter: MTeamAdapter,
    *,
    min_size_gb: float = 10.0,
    topping_only: bool = True,
    page_size: int = 200,
    max_pages: int = 3,
    include_mall_free: bool = True,
) -> FreeToppedResult:
    """Two-pass search: discount=FREE + mallSingleFree, then filter and group by topping level."""
    import logging
    logger = logging.getLogger(__name__)
    seen_ids: set[str] = set()
    all_items: list[dict[str, Any]] = []

    # Pass 1: discount=FREE
    for page in range(1, max_pages + 1):
        items = adapter.search_raw(page=page, page_size=page_size, discount="FREE")
        if not items:
            break
        for item in items:
            tid = str(item.get("id", "")).strip()
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                all_items.append(item)
    logger.info("Free-topped Pass 1 (discount=FREE): %d unique", len(all_items))

    # Pass 2: no discount filter -> mallSingleFree only
    if include_mall_free:
        mall_pages = max(1, max_pages // 2)
        for page in range(1, mall_pages + 1):
            items = adapter.search_raw(page=page, page_size=page_size)
            if not items:
                break
            mall_count = 0
            for item in items:
                tid = str(item.get("id", "")).strip()
                if not tid or tid in seen_ids:
                    continue
                status = item.get("status")
                if not isinstance(status, dict) or not isinstance(status.get("mallSingleFree"), dict):
                    continue
                seen_ids.add(tid)
                all_items.append(item)
                mall_count += 1
            logger.info("Free-topped Pass 2 (mallSingleFree) page %d: %d new", page, mall_count)

    # Filter and extract
    min_bytes = _gb_to_bytes(min_size_gb)
    result = FreeToppedResult()

    for item in all_items:
        c = _extract_candidate(item)

        # Size filter
        if c.size_bytes < min_bytes:
            continue

        # FREE check
        is_free = (c.discount in FREE_DISCOUNTS) or _has_mall(item)
        if not is_free:
            continue

        # Topping filter
        if topping_only and c.topping_level < 1:
            continue

        if c.topping_level >= 2:
            result.level2_torrents.append(c)
        elif c.topping_level == 1:
            result.level1_torrents.append(c)

    # Sort each level by size desc
    result.level2_torrents.sort(key=lambda t: t.size_bytes, reverse=True)
    result.level1_torrents.sort(key=lambda t: t.size_bytes, reverse=True)

    logger.info("Free-topped result: level2=%d level1=%d",
                 len(result.level2_torrents), len(result.level1_torrents))
    return result


def _has_mall(item: dict[str, Any]) -> bool:
    status = item.get("status")
    return isinstance(status, dict) and isinstance(status.get("mallSingleFree"), dict)
