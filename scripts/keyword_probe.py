from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.adapters.mteam import MTeamAdapter
from app.config import get_settings


def summarize_results(keyword: str, rows: list[dict[str, Any]], top_n: int = 3) -> dict[str, Any]:
    """Convert raw adapter rows into a small, repeatable probe summary."""

    top_candidates = [
        {
            "id": str(row.get("id", "")),
            "title": str(row.get("title") or row.get("name") or ""),
            "seeders": int(row.get("seeders", 0) or 0),
            "size": row.get("size"),
            "size_bytes": row.get("size_bytes"),
        }
        for row in rows[:top_n]
    ]
    return {
        "keyword": keyword,
        "result_count": len(rows),
        "top_candidates": top_candidates,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe M-Team keyword sensitivity without going through workflow.",
    )
    parser.add_argument("keywords", nargs="+", help="One or more keywords to search directly against M-Team.")
    parser.add_argument("--page", type=int, default=1, help="Search results page number.")
    parser.add_argument("--page-size", type=int, default=20, help="Search page size sent to M-Team.")
    parser.add_argument("--top", type=int, default=3, help="How many top candidates to keep in the summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    adapter = MTeamAdapter(
        base_url=settings.mteam_base_url,
        api_key=settings.mteam_api_key,
    )

    summaries: list[dict[str, Any]] = []
    for keyword in args.keywords:
        rows = adapter.search_torrents_by_keyword(
            keyword=keyword,
            page=args.page,
            page_size=args.page_size,
        )
        summaries.append(summarize_results(keyword, rows, top_n=args.top))

    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
