import os

import pytest

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.config import get_settings


def _require_connectivity_settings():
    settings = get_settings()
    missing = [
        name
        for name, value in {
            "MTEAM_BASE_URL": settings.mteam_base_url,
            "MTEAM_API_KEY": settings.mteam_api_key,
            "QB_BASE_URL": settings.qb_base_url,
            "QB_USERNAME": settings.qb_username,
            "QB_PASSWORD": settings.qb_password,
        }.items()
        if not value
    ]
    assert not missing, f"Missing required connectivity settings: {', '.join(missing)}"
    return settings


@pytest.mark.skipif(not os.getenv("RUN_CONNECTIVITY_TESTS"), reason="integration-only")
def test_connectivity_settings_are_present():
    settings = _require_connectivity_settings()

    assert settings.mteam_api_key, "MTEAM_API_KEY should be set for connectivity tests"
    assert settings.mteam_base_url, "MTEAM_BASE_URL should be set for connectivity tests"
    assert settings.qb_base_url, "QB_BASE_URL should be set for connectivity tests"
    assert settings.qb_username, "QB_USERNAME should be set for connectivity tests"
    assert settings.qb_password, "QB_PASSWORD should be set for connectivity tests"


@pytest.mark.skipif(not os.getenv("RUN_CONNECTIVITY_TESTS"), reason="integration-only")
def test_connectivity_services_reach_real_endpoints():
    settings = _require_connectivity_settings()

    mteam = MTeamAdapter(
        base_url=settings.mteam_base_url,
        api_key=settings.mteam_api_key,
    )
    results = mteam.search_torrents_by_keyword(keyword="Dune", page=1, page_size=1)
    assert isinstance(results, list), "M-Team search should return a list even when empty"

    qb = QBittorrentAdapter(
        base_url=settings.qb_base_url,
        username=settings.qb_username,
        password=settings.qb_password,
    )
    client = qb.login()
    assert client is not None, "qB login should return an authenticated client"
    categories = qb.list_categories()
    assert isinstance(categories, dict), "qB category listing should return a dict"
