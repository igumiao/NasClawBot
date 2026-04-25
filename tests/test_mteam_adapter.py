import pytest

from app.adapters.mteam import MTeamAdapter


def test_mteam_search_payload_contains_keyword_and_paging():
    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")
    payload = adapter.build_search_payload(keyword="dune", page=2)

    assert payload["keyword"] == "dune"
    assert payload["pageNumber"] == 2
    assert payload["pageSize"] == 20
    assert payload["mode"] == "normal"


def test_mteam_endpoints_normalize_trailing_slash():
    adapter = MTeamAdapter(base_url="https://example.com/", api_key="secret")

    assert adapter.search_endpoint() == "https://example.com/api/torrent/search"
    assert adapter.detail_endpoint() == "https://example.com/api/torrent/detail"
    assert adapter.download_token_endpoint() == "https://example.com/api/torrent/genDlToken"


def test_mteam_empty_keyword_raises_value_error():
    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")

    with pytest.raises(ValueError):
        adapter.build_search_payload(keyword="   ")
