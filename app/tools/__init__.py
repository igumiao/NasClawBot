"""NasClawBot tool wrappers.

Each tool wraps an existing adapter operation behind the Tool protocol.
"""

from app.tools.current_time import CurrentTimeTool
from app.tools.member_profile import MemberProfileTool
from app.tools.memory_search import MemorySearchTool
from app.tools.remember_this import RememberThisTool
from app.tools.mteam_search import MTeamSearchTool
from app.tools.qb_add_torrent import QBAddTorrentTool
from app.tools.qb_add_torrents import QBAddTorrentsTool
from app.tools.qb_list_torrents import QBListTorrentsTool
from app.tools.qb_get_torrent import QBGetTorrentTool
from app.tools.qb_list_categories import QBListCategoriesTool  # deprecated — kept for compat
from app.tools.qb_list_tags import QBListTagsTool
from app.tools.qb_control_torrent import QBControlTorrentTool
from app.tools.qb_set_global_speed import QBSetGlobalSpeedTool
from app.tools.qb_set_torrent_speed import QBSetTorrentSpeedTool
from app.tools.tavily_search import TavilySearchTool
from app.tools.tmdb_search import TMDBSearchTool
from app.tools.tmdb_details import TMDBDetailsTool
from app.tools.tmdb_discover import TMDBDiscoverTool
from app.tools.tmdb_trending import TMDBTrendingTool
from app.tools.monitor_download import MonitorDownloadTool
from app.tools.task_list import TaskListTool
from app.tools.task_cancel import TaskCancelTool
from app.tools.update_download_monitor import UpdateDownloadMonitorTool
from app.tools.list_task_events import ListTaskEventsTool

__all__ = [
    "CurrentTimeTool",
    "MemberProfileTool",
    "MemorySearchTool",
    "RememberThisTool",
    "MTeamSearchTool",
    "QBAddTorrentTool",
    "QBAddTorrentsTool",
    "QBListTorrentsTool",
    "QBGetTorrentTool",
    "QBListCategoriesTool",  # deprecated
    "QBListTagsTool",
    "QBControlTorrentTool",
    "QBSetGlobalSpeedTool",
    "QBSetTorrentSpeedTool",
    "TavilySearchTool",
    "TMDBSearchTool",
    "TMDBDetailsTool",
    "TMDBDiscoverTool",
    "TMDBTrendingTool",
    "MonitorDownloadTool",
    "TaskListTool",
    "TaskCancelTool",
    "UpdateDownloadMonitorTool",
    "ListTaskEventsTool",
]
