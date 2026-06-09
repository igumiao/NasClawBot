"""Search M-Team for topped + FREE torrents suitable for ratio boosting.

Usage:
  # Default: toppingLevel>=1, FREE, min 10GB, scan first 200 results
  .venv/bin/python probes/mteam/free_topped_finder.py

  # Custom size threshold
  .venv/bin/python probes/mteam/free_topped_finder.py --min-size 40

  # Include all FREE (not just topped), scan 3 pages
  .venv/bin/python probes/mteam/free_topped_finder.py --all-free --max-pages 3

  # Also search _2X_FREE (double upload + free)
  .venv/bin/python probes/mteam/free_topped_finder.py --discount _2X_FREE

  # Minimum leechers filter
  .venv/bin/python probes/mteam/free_topped_finder.py --min-leechers 10

  # Sort by leecher count instead of default (size)
  .venv/bin/python probes/mteam/free_topped_finder.py --sort-by leechers

Output is a human-readable table. Use --json for machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings  # noqa: E402

DISCOUNT_CHOICES = ["FREE", "_2X_FREE", "_2X_PERCENT_50"]
SORT_BY_CHOICES = ["size", "seeders", "leechers", "default"]


@dataclass
class Candidate:
    id: str
    name: str
    size_bytes: int
    size_display: str
    seeders: int
    leechers: int
    discount: str
    discount_end: str | None
    topping_level: str
    topping_end: str | None
    mall_single_free: bool
    mall_free_end: str | None
    category: str
    created: str
    imdb: str | None
    douban: str | None
    team: str | None


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


def _extract_candidate(item: dict[str, Any]) -> Candidate:
    status = item.get("status")
    if not isinstance(status, dict):
        status = {}

    size_bytes = _coerce_int(item.get("size"))
    mall = status.get("mallSingleFree")

    return Candidate(
        id=str(item.get("id", "")).strip(),
        name=str(item.get("name", "")).strip(),
        size_bytes=size_bytes,
        size_display=_format_size(size_bytes),
        seeders=_coerce_int(status.get("seeders")),
        leechers=_coerce_int(status.get("leechers")),
        discount=str(status.get("discount") or "").strip() or "?",
        discount_end=str(status.get("discountEndTime") or "").strip() or None,
        topping_level=str(status.get("toppingLevel", "0")).strip(),
        topping_end=str(status.get("toppingEndTime") or "").strip() or None,
        mall_single_free=isinstance(mall, dict),
        mall_free_end=str(mall.get("endDate") or "").strip() if isinstance(mall, dict) else None,
        category=str(item.get("category", "")).strip(),
        created=str(item.get("createdDate", "")).strip(),
        imdb=str(item.get("imdb") or "").strip() or None,
        douban=str(item.get("douban") or "").strip() or None,
        team=str(item.get("team") or "").strip() or None,
    )


def _fetch_pages(
    client: httpx.Client,
    *,
    discount: str | None = None,
    page_size: int = 200,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    """Fetch pages from M-Team search. If discount is None, no discount filter."""
    items: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload: dict[str, Any] = {
            "mode": "normal",
            "keyword": "",
            "pageNumber": page,
            "pageSize": min(page_size, 200),
            "visible": 1,
        }
        if discount is not None:
            payload["discount"] = discount
        try:
            resp = client.post("/api/torrent/search", json=payload)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") not in ("0", 0) and str(body.get("message", "")).upper() != "SUCCESS":
                print(f"[WARN] Page {page}: API error — {body.get('message', '?')}", file=sys.stderr)
                break
            data = body.get("data")
            if not isinstance(data, dict):
                break
            batch = data.get("data", [])
            if not isinstance(batch, list) or not batch:
                break
            items.extend(batch)
        except httpx.HTTPError as exc:
            print(f"[WARN] Page {page} HTTP error: {exc}", file=sys.stderr)
            break
    return items


def search_free_torrents(
    api_key: str,
    base_url: str,
    *,
    discount: str = "FREE",
    page_size: int = 200,
    max_pages: int = 5,
    include_mall_free: bool = True,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Fetch FREE + mallSingleFree torrents from M-Team.

    Two-pass search:
    1. discount=FREE (catches most FREE torrents, including topped)
    2. No discount filter → keep only mallSingleFree (catches community-funded free torrents
       whose base discount is PERCENT_50 or NORMAL, missed by pass 1)
    """
    base = base_url.rstrip("/")
    seen_ids: set[str] = set()
    all_items: list[dict[str, Any]] = []

    with httpx.Client(
        base_url=base,
        headers={"x-api-key": api_key},
        timeout=timeout,
    ) as client:
        # Pass 1: discount-filtered search
        items = _fetch_pages(client, discount=discount, page_size=page_size, max_pages=max_pages)
        for item in items:
            tid = str(item.get("id", "")).strip()
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                all_items.append(item)
        print(f"[INFO] Pass 1 (discount={discount}): {len(items)} raw, {len(all_items)} unique",
              file=sys.stderr)

        # Pass 2: no discount filter → mallSingleFree only
        if include_mall_free:
            mall_items = _fetch_pages(client, discount=None, page_size=page_size, max_pages=max(1, max_pages // 2))
            mall_count = 0
            for item in mall_items:
                tid = str(item.get("id", "")).strip()
                if not tid or tid in seen_ids:
                    continue
                status = item.get("status")
                if not isinstance(status, dict) or not isinstance(status.get("mallSingleFree"), dict):
                    continue
                seen_ids.add(tid)
                all_items.append(item)
                mall_count += 1
            print(f"[INFO] Pass 2 (mallSingleFree): {len(mall_items)} raw, {mall_count} new unique",
                  file=sys.stderr)

    return all_items


def filter_candidates(
    items: list[dict[str, Any]],
    *,
    min_size_bytes: int = 0,
    min_leechers: int = 0,
    topping_only: bool = True,
) -> list[Candidate]:
    """Extract and filter candidates from raw search results.

    FREE is defined as EITHER:
      - discount in {FREE, _2X_FREE, _2X_PERCENT_50, _2X} (API-level free)
      - Has active mallSingleFree (community-funded free, base discount could be anything)
    """
    free_discounts = {"FREE", "_2X_FREE", "_2X_PERCENT_50", "_2X"}
    candidates: list[Candidate] = []
    for item in items:
        c = _extract_candidate(item)

        # Size filter
        if c.size_bytes < min_size_bytes:
            continue

        # Leecher filter
        if c.leechers < min_leechers:
            continue

        # FREE check — must pass at least one of:
        #   a) API-level free discount
        #   b) Active mallSingleFree (community-funded)
        is_free = c.discount in free_discounts or c.mall_single_free
        if not is_free:
            continue

        # Topping filter
        if topping_only:
            topping_level = _coerce_int(c.topping_level)
            if topping_level < 1 and not c.mall_single_free:
                # mallSingleFree is inherently user-funded topping, count it
                continue

        candidates.append(c)

    return candidates


def print_table(candidates: list[Candidate]) -> None:
    """Pretty-print candidates as a human-readable table."""
    if not candidates:
        print("没有找到匹配的种子。")
        return

    # Column widths
    id_w = max(8, max(len(c.id) for c in candidates))
    name_w = min(70, max(len(c.name) for c in candidates))
    size_w = 9
    s_w = 5
    l_w = 5
    disc_w = 18
    free_end_w = 19

    header = (
        f"{'ID':>{id_w}}  {'名称':<{name_w}}  {'大小':>{size_w}}  "
        f"{'做种':>{s_w}}  {'下载':>{l_w}}  "
        f"{'优惠':<{disc_w}}  {'免费截止':<{free_end_w}}  {'置顶':>4}  mall"
    )
    print(header)
    print("-" * len(header))

    for c in candidates:
        topping_str = c.topping_level if c.topping_level != "0" else "-"
        mall_str = "✓" if c.mall_single_free else ""
        # For mallSingleFree torrents, the real free deadline is mall_free_end
        free_end = c.mall_free_end or c.discount_end or "-"
        # Truncate free_end for display
        if free_end and len(free_end) > 19:
            free_end = free_end[:16] + "..."

        name = c.name[:name_w]
        # Show effective discount: "PERCENT_50→FREE" for mallSingleFree
        disc_display = f"{c.discount}→FREE" if c.mall_single_free and c.discount not in ("FREE", "_2X_FREE") else c.discount
        print(
            f"{c.id:>{id_w}}  {name:<{name_w}}  {c.size_display:>{size_w}}  "
            f"{c.seeders:>{s_w}}  {c.leechers:>{l_w}}  "
            f"{disc_display:<{disc_w}}  {free_end:<{free_end_w}}  {topping_str:>4}  {mall_str}"
        )

    print()
    print(f"共 {len(candidates)} 条匹配")


def print_json(candidates: list[Candidate]) -> None:
    """Output candidates as JSON."""
    result = []
    for c in candidates:
        result.append(
            {
                "id": c.id,
                "name": c.name,
                "size": c.size_display,
                "size_bytes": c.size_bytes,
                "seeders": c.seeders,
                "leechers": c.leechers,
                "discount": c.discount,
                "discount_end": c.discount_end,
                "topping_level": c.topping_level,
                "topping_end": c.topping_end,
                "mall_single_free": c.mall_single_free,
                "mall_free_end": c.mall_free_end,
                "category": c.category,
                "created": c.created,
                "imdb": c.imdb,
                "douban": c.douban,
            }
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="查找 M-Team 置顶免费种子，用于刷上传量。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                           # 默认: >=10GB, topping>=1, FREE
  %(prog)s --min-size 40             # 只要 >=40GB 的大包
  %(prog)s --all-free                # 包括非置顶的 FREE 种子
  %(prog)s --min-leechers 20         # 至少有 20 人在下载
  %(prog)s --sort-by leechers        # 按下人数排序
  %(prog)s --max-pages 3 --json      # 扫 3 页, JSON 输出
        """,
    )
    parser.add_argument("--min-size", type=float, default=10.0,
                        help="最小体积 (GB), 默认 10")
    parser.add_argument("--min-leechers", type=int, default=0,
                        help="最少下载人数, 默认 0 (不过滤)")
    parser.add_argument("--discount", choices=DISCOUNT_CHOICES, default="FREE",
                        help="优惠类型, 默认 FREE")
    parser.add_argument("--page-size", type=int, default=200,
                        help="每页条数 (最大 200), 默认 200")
    parser.add_argument("--max-pages", type=int, default=3,
                        help="最大扫描页数, 默认 3 (最多 600 条)")
    parser.add_argument("--all-free", action="store_true",
                        help="包括非置顶的 FREE 种子 (默认只选 toppingLevel>=1 或 mallSingleFree)")
    parser.add_argument("--no-mall-free", action="store_true",
                        help="跳过 mallSingleFree 搜索 (只搜 discount=FREE)")
    parser.add_argument("--sort-by", choices=SORT_BY_CHOICES, default="size",
                        help="排序方式, 默认 size (体积降序)")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="JSON 格式输出 (机器可读)")
    parser.add_argument("--timeout", type=float, default=15.0,
                        help="HTTP 超时秒数, 默认 15")

    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.mteam_api_key:
        print("错误: MTEAM_API_KEY 未配置", file=sys.stderr)
        return 1

    # Fetch
    topping_only = not args.all_free
    min_bytes = _gb_to_bytes(args.min_size)

    items = search_free_torrents(
        api_key=settings.mteam_api_key,
        base_url=settings.mteam_base_url,
        discount=args.discount,
        page_size=args.page_size,
        max_pages=args.max_pages,
        include_mall_free=not args.no_mall_free,
        timeout=args.timeout,
    )
    print(f"[INFO] 拉取 {len(items)} 条原始结果", file=sys.stderr)

    # Filter
    candidates = filter_candidates(
        items,
        min_size_bytes=min_bytes,
        min_leechers=args.min_leechers,
        topping_only=topping_only,
    )
    print(f"[INFO] 筛选后 {len(candidates)} 条匹配", file=sys.stderr)

    # Sort
    sort_key_map = {
        "size": lambda c: c.size_bytes,
        "seeders": lambda c: c.seeders,
        "leechers": lambda c: c.leechers,
        "default": lambda c: 0,
    }
    candidates.sort(key=sort_key_map[args.sort_by], reverse=(args.sort_by != "default"))

    # Output
    if args.json_output:
        print_json(candidates)
    else:
        print()
        print(f"  discount={args.discount}  min_size={args.min_size}GB  "
              f"min_leechers={args.min_leechers}  topping_only={topping_only}")
        print()
        print_table(candidates)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
