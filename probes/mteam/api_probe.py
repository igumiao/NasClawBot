"""M-Team API probe tool for exploring undocumented endpoints and search parameters.

Usage:
  # Lookup endpoints (return valid IDs for search filters)
  .venv/bin/python probes/mteam/api_probe.py category-list
  .venv/bin/python probes/mteam/api_probe.py source-list
  .venv/bin/python probes/mteam/api_probe.py medium-list
  .venv/bin/python probes/mteam/api_probe.py standard-list
  .venv/bin/python probes/mteam/api_probe.py video-codec-list
  .venv/bin/python probes/mteam/api_probe.py audio-codec-list
  .venv/bin/python probes/mteam/api_probe.py processing-list
  .venv/bin/python probes/mteam/api_probe.py team-list

  # Torrent detail endpoints
  .venv/bin/python probes/mteam/api_probe.py files --id 1163290
  .venv/bin/python probes/mteam/api_probe.py media-info --id 1163290
  .venv/bin/python probes/mteam/api_probe.py peers --id 1163290

  # Media metadata endpoints
  .venv/bin/python probes/mteam/api_probe.py douban-elessar --code 1292052
  .venv/bin/python probes/mteam/api_probe.py douban-info --code 1292052
  .venv/bin/python probes/mteam/api_probe.py imdb-info --code tt0111161

  # Search with various parameters
  .venv/bin/python probes/mteam/api_probe.py search --keyword "dune" --mode movie
  .venv/bin/python probes/mteam/api_probe.py search --keyword "dune" --sort-field SEEDERS --sort-direction DESC
  .venv/bin/python probes/mteam/api_probe.py search --keyword "dune" --discount FREE
  .venv/bin/python probes/mteam/api_probe.py search --keyword "spider" --imdb tt0145487
  .venv/bin/python probes/mteam/api_probe.py search --keyword "phantom" --douban 1292052
  .venv/bin/python probes/mteam/api_probe.py search --keyword "dune" --categories 419 421 --sources 1 --mediums 1
  .venv/bin/python probes/mteam/api_probe.py search --keyword "dune" --hot --only-fav

All commands print the full request and response JSON to stdout. Use --raw for JSON-only output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings  # noqa: E402

# ---------------------------------------------------------------------------
# Enums from swagger TorrentSearch schema
# ---------------------------------------------------------------------------

MODE_CHOICES = ["normal", "adult", "movie", "music", "tvshow", "waterfall", "rss", "rankings", "all"]

SORT_FIELD_CHOICES = ["CREATED_DATE", "SIZE", "SEEDERS", "LEECHERS", "TIMES_COMPLETED", "NAME"]
SORT_DIRECTION_CHOICES = ["ASC", "DESC"]

DISCOUNT_CHOICES = [
    "NORMAL", "PERCENT_70", "PERCENT_50", "FREE",
    "_2X_FREE", "_2X", "_2X_PERCENT_50",
]

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_client(timeout: float = 15.0) -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.mteam_base_url.rstrip("/"),
        headers={"x-api-key": settings.mteam_api_key},
        timeout=timeout,
    )


def _print_result(client: httpx.Client, method: str, path: str, *,
                  query_params: dict[str, Any] | None = None,
                  json_body: dict[str, Any] | None = None,
                  data_body: dict[str, Any] | None = None,
                  raw: bool = False) -> None:
    """Execute a request and print request/response details."""

    url = f"{client.base_url}{path}"
    if query_params:
        url += f"?{urlencode(query_params)}"

    if not raw:
        print("=" * 72)
        print(f"REQUEST: {method} {url}")
        if json_body is not None:
            print(f"Body (JSON): {json.dumps(json_body, ensure_ascii=False, indent=2)}")
        if data_body is not None:
            print(f"Body (form-data): {json.dumps(data_body, ensure_ascii=False, indent=2)}")
        print("-" * 72)

    try:
        if method == "GET":
            resp = client.get(path, params=query_params or {})
        elif json_body is not None:
            resp = client.post(path, params=query_params or {}, json=json_body)
        elif data_body is not None:
            resp = client.post(path, params=query_params or {}, data=data_body)
        else:
            resp = client.post(path, params=query_params or {})

        if not raw:
            print(f"RESPONSE: HTTP {resp.status_code}")
            print(f"Content-Type: {resp.headers.get('content-type', '?')}")
            print("-" * 72)

        try:
            parsed = resp.json()
        except (json.JSONDecodeError, ValueError):
            if not raw:
                print("[non-JSON response — printing raw text]")
            print(resp.text)
            return

        if raw:
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
            print("=" * 72)

    except httpx.HTTPError as exc:
        print(f"HTTP ERROR: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Generic lookup-list endpoint (no params, returns Result)
# ---------------------------------------------------------------------------

def _make_lookup_cmd(label: str, endpoint: str):
    """Factory for subcommands that call a no-parameter list endpoint."""
    def _cmd(args: argparse.Namespace) -> None:
        with _build_client() as client:
            _print_result(client, "POST", endpoint, raw=args.raw)
    _cmd.__name__ = label
    _cmd.__doc__ = f"Probe {endpoint}"
    return _cmd


# ---------------------------------------------------------------------------
# Generic id-based endpoint
# ---------------------------------------------------------------------------

def _make_id_cmd(endpoint: str, use_data_body: bool = True):
    """Factory for subcommands that call an endpoint with an id parameter."""
    def _cmd(args: argparse.Namespace) -> None:
        with _build_client() as client:
            kwargs = {}
            if use_data_body:
                kwargs["data_body"] = {"id": args.id}
            else:
                kwargs["query_params"] = {"id": args.id}
            _print_result(client, "POST", endpoint, raw=args.raw, **kwargs)
    _cmd.__name__ = endpoint.replace("/", "_")
    return _cmd


# ---------------------------------------------------------------------------
# Media endpoint with dual-path probing
# ---------------------------------------------------------------------------

def _make_media_cmd(path: str):
    """Factory for media endpoint subcommands (all use /api prefix)."""
    def _cmd(args: argparse.Namespace) -> None:
        params = {"code": args.code, "refresh": str(args.refresh).lower()}
        with _build_client() as client:
            _print_result(client, "POST", path, query_params=params, raw=args.raw)
    return _cmd


# ---------------------------------------------------------------------------
# Subcommand: search
# ---------------------------------------------------------------------------

def cmd_search(args: argparse.Namespace) -> None:
    """Probe /api/torrent/search with the full TorrentSearch schema."""
    payload: dict[str, Any] = {
        "mode": args.mode,
        "keyword": args.keyword,
        "pageNumber": args.page_number,
        "pageSize": args.page_size,
        "visible": args.visible,
    }

    if args.last_id is not None:
        payload["lastId"] = args.last_id
    if args.author_id is not None:
        payload["authorId"] = args.author_id
    if args.author is not None:
        payload["author"] = args.author

    # Array filters
    if args.categories:
        payload["categories"] = [int(c) for c in args.categories]
    if args.sources:
        payload["sources"] = [int(s) for s in args.sources]
    if args.mediums:
        payload["mediums"] = [int(m) for m in args.mediums]
    if args.standards:
        payload["standards"] = [int(s) for s in args.standards]
    if args.video_codecs:
        payload["videoCodecs"] = [int(v) for v in args.video_codecs]
    if args.audio_codecs:
        payload["audioCodecs"] = [int(a) for a in args.audio_codecs]
    if args.teams:
        payload["teams"] = [int(t) for t in args.teams]
    if args.processings:
        payload["processings"] = [int(p) for p in args.processings]
    if args.countries:
        payload["countries"] = [int(c) for c in args.countries]

    # String filters
    if args.imdb:
        payload["imdb"] = args.imdb
    if args.douban:
        payload["douban"] = args.douban
    if args.dmm_code:
        payload["dmmCode"] = args.dmm_code

    # Enum filters
    if args.discount:
        payload["discount"] = args.discount
    if args.sort_field:
        payload["sortField"] = args.sort_field
    if args.sort_direction:
        payload["sortDirection"] = args.sort_direction

    # Other filters
    if args.labels is not None:
        payload["labels"] = args.labels
    if args.labels_new:
        payload["labelsNew"] = list(args.labels_new)
    if args.upload_date_start:
        payload["uploadDateStart"] = args.upload_date_start
    if args.upload_date_end:
        payload["uploadDateEnd"] = args.upload_date_end
    if args.fav_date_limit:
        payload["favDateLimit"] = args.fav_date_limit
    if args.hot:
        payload["hot"] = True
    if args.only_fav:
        payload["onlyFav"] = True
    if args.offer:
        payload["offer"] = True
    if args.with_cache:
        payload["withCache"] = True

    with _build_client(timeout=args.timeout) as client:
        _print_result(
            client, "POST", "/api/torrent/search",
            json_body=payload,
            raw=args.raw,
        )


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M-Team API probe — explore endpoints and parameters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--raw", action="store_true", help="Output only the response JSON.")
    sub = parser.add_subparsers(dest="command", required=True)

    # -----------------------------------------------------------------------
    # Lookup endpoints (no params)
    # -----------------------------------------------------------------------
    lookups = [
        ("category-list",     "/api/torrent/categoryList",     "List all torrent categories."),
        ("source-list",       "/api/torrent/sourceList",       "List all source types (BluRay, WEB-DL, etc.)."),
        ("medium-list",       "/api/torrent/mediumList",       "List all medium types (UHD, BD, DVD, etc.)."),
        ("standard-list",     "/api/torrent/standardList",     "List all standard/resolution options."),
        ("video-codec-list",  "/api/torrent/videoCodecList",   "List all video codec options."),
        ("audio-codec-list",  "/api/torrent/audioCodecList",   "List all audio codec options."),
        ("processing-list",   "/api/torrent/processingList",   "List all processing types (Remux, Encode, etc.)."),
        ("team-list",         "/api/torrent/teamList",         "List all team/group options."),
    ]
    for name, endpoint, help_text in lookups:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=_make_lookup_cmd(name, endpoint))

    # -----------------------------------------------------------------------
    # ID-based endpoints (data_body)
    # -----------------------------------------------------------------------
    p_files = sub.add_parser("files", help="List files inside a torrent (/api/torrent/files).")
    p_files.add_argument("--id", required=True, help="M-Team torrent id.")
    p_files.set_defaults(func=_make_id_cmd("/api/torrent/files", use_data_body=True))

    p_media = sub.add_parser("media-info", help="Media metadata for a torrent (/api/torrent/mediaInfo).")
    p_media.add_argument("--id", required=True, help="M-Team torrent id.")
    p_media.set_defaults(func=_make_id_cmd("/api/torrent/mediaInfo", use_data_body=True))

    p_peers = sub.add_parser("peers", help="List peers for a torrent (/api/torrent/peers).")
    p_peers.add_argument("--id", required=True, help="M-Team torrent id.")
    p_peers.set_defaults(func=_make_id_cmd("/api/torrent/peers", use_data_body=True))

    # -----------------------------------------------------------------------
    # Media endpoints (all use /api prefix)
    # -----------------------------------------------------------------------
    p_elessar = sub.add_parser("douban-elessar", help="Douban elessarV2 info (/api/media/douban/elessarV2).")
    p_elessar.add_argument("--code", required=True, help="Douban subject code (e.g. 1292052).")
    p_elessar.add_argument("--refresh", type=lambda x: x.lower() in ("true", "1", "yes"), default=False,
                           help="Force refresh (default: false).")
    p_elessar.set_defaults(func=_make_media_cmd("/api/media/douban/elessarV2"))

    p_douban = sub.add_parser("douban-info", help="Douban infoV2 (/api/media/douban/infoV2).")
    p_douban.add_argument("--code", required=True, help="Douban subject code (e.g. 1292052).")
    p_douban.add_argument("--refresh", type=lambda x: x.lower() in ("true", "1", "yes"), default=False,
                          help="Force refresh (default: false).")
    p_douban.set_defaults(func=_make_media_cmd("/api/media/douban/infoV2"))

    p_imdb = sub.add_parser("imdb-info", help="IMDB info (/api/media/imdb/info).")
    p_imdb.add_argument("--code", required=True, help="IMDB id (e.g. tt0111161).")
    p_imdb.add_argument("--refresh", type=lambda x: x.lower() in ("true", "1", "yes"), default=False,
                        help="Force refresh (default: false).")
    p_imdb.set_defaults(func=_make_media_cmd("/api/media/imdb/info"))

    # -----------------------------------------------------------------------
    # Search
    # -----------------------------------------------------------------------
    p_search = sub.add_parser("search", help="Search torrents with full TorrentSearch parameters.",
                              formatter_class=argparse.RawDescriptionHelpFormatter)
    p_search.add_argument("--keyword", required=True, help="Search keyword.")
    p_search.add_argument("--mode", choices=MODE_CHOICES, default="normal",
                          help="Search mode. 'movie' = movies only, 'tvshow' = TV only, "
                               "'adult' = adult, 'music' = music, 'rss' = RSS feed, "
                               "'rankings' = rankings, 'waterfall' = waterfall layout, "
                               "'all' = all content. (default: normal)")
    p_search.add_argument("--page-number", type=int, default=1)
    p_search.add_argument("--page-size", type=int, default=10)
    p_search.add_argument("--last-id", type=int, help="Cursor-based pagination (int64).")
    p_search.add_argument("--visible", type=int, default=1, help="Visibility filter (default: 1).")

    # Array filters
    af = p_search.add_argument_group("Array filters (use IDs from lookup endpoints)")
    af.add_argument("--categories", nargs="*", help="Category IDs (from category-list).")
    af.add_argument("--sources", nargs="*", help="Source IDs (from source-list).")
    af.add_argument("--mediums", nargs="*", help="Medium IDs (from medium-list).")
    af.add_argument("--standards", nargs="*", help="Standard/resolution IDs (from standard-list).")
    af.add_argument("--video-codecs", nargs="*", help="Video codec IDs (from video-codec-list).")
    af.add_argument("--audio-codecs", nargs="*", help="Audio codec IDs (from audio-codec-list).")
    af.add_argument("--teams", nargs="*", help="Team/group IDs (from team-list).")
    af.add_argument("--processings", nargs="*", help="Processing IDs (from processing-list).")
    af.add_argument("--countries", nargs="*", help="Country IDs.")
    af.add_argument("--labels-new", nargs="*", help="New-style label strings.")

    # String filters
    sf = p_search.add_argument_group("String filters")
    sf.add_argument("--imdb", help="Filter by IMDB id (e.g. tt0145487).")
    sf.add_argument("--douban", help="Filter by douban subject id (e.g. 1292052).")
    sf.add_argument("--dmm-code", help="Filter by DMM code.")

    # Enum filters
    ef = p_search.add_argument_group("Enum filters")
    ef.add_argument("--sort-field", choices=SORT_FIELD_CHOICES,
                    help="Sort field: CREATED_DATE, SIZE, SEEDERS, LEECHERS, TIMES_COMPLETED, NAME.")
    ef.add_argument("--sort-direction", choices=SORT_DIRECTION_CHOICES,
                    help="Sort direction: ASC or DESC.")
    ef.add_argument("--discount", choices=DISCOUNT_CHOICES,
                    help="Discount filter: NORMAL, PERCENT_70, PERCENT_50, FREE, _2X_FREE, _2X, _2X_PERCENT_50.")

    # Other filters
    of = p_search.add_argument_group("Other filters")
    of.add_argument("--author-id", type=int, help="Filter by author/uploader ID.")
    of.add_argument("--author", type=int, help="Filter by author ID (alternative).")
    of.add_argument("--labels", type=int, help="Label filter ID (old-style).")
    of.add_argument("--upload-date-start", help="Upload date start (ISO datetime).")
    of.add_argument("--upload-date-end", help="Upload date end (ISO datetime).")
    of.add_argument("--fav-date-limit", help="Favorites date limit (ISO datetime).")
    of.add_argument("--hot", action="store_true", help="Hot torrents only.")
    of.add_argument("--only-fav", action="store_true", help="Favorites only.")
    of.add_argument("--offer", action="store_true", help="Offer torrents only.")
    of.add_argument("--with-cache", action="store_true", help="Include cache info.")
    of.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds.")

    p_search.set_defaults(func=cmd_search)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
