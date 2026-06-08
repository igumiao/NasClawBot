"""NasClawBot tool wrappers.

Each tool wraps an existing adapter operation behind the Tool protocol.
"""

from app.tools.member_profile import MemberProfileTool
from app.tools.mteam_search import MTeamSearchTool
from app.tools.qb_add_torrent import QBAddTorrentTool
from app.tools.qb_get_torrent import QBGetTorrentTool
from app.tools.qb_list_categories import QBListCategoriesTool

__all__ = [
    "MemberProfileTool",
    "MTeamSearchTool",
    "QBAddTorrentTool",
    "QBGetTorrentTool",
    "QBListCategoriesTool",
]
