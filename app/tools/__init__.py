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
from app.tools.tavily_search import TavilySearchTool
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
    "TavilySearchTool",
    "TMDBSearchTool",
    "TMDBDetailsTool",
    "TMDBDiscoverTool",
    "TMDBTrendingTool",
]
