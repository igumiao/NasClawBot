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
]
