import pytest

import app.adapters.mteam as mteam_module
from app.adapters.mteam import MTeamAdapter


def test_mteam_search_payload_contains_keyword_and_paging():
    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")
    payload = adapter.build_search_payload(keyword="dune", page=2)

    assert payload["keyword"] == "dune"
    assert payload["pageNumber"] == 2
    assert payload["pageSize"] == 20
    assert payload["mode"] == "normal"
    assert payload["visible"] == 1


def test_mteam_endpoints_normalize_trailing_slash():
    adapter = MTeamAdapter(base_url="https://example.com/", api_key="secret")

    assert adapter.search_endpoint() == "https://example.com/api/torrent/search"
    assert adapter.detail_endpoint() == "https://example.com/api/torrent/detail"
    assert adapter.download_token_endpoint() == "https://example.com/api/torrent/genDlToken"


def test_mteam_empty_keyword_raises_value_error():
    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")

    with pytest.raises(ValueError):
        adapter.build_search_payload(keyword="   ")


def test_mteam_headers_only_include_api_key():
    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")

    headers = adapter.build_headers()

    assert headers == {"x-api-key": "secret"}


def test_mteam_success_response_accepts_string_or_numeric_zero_code():
    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")

    assert adapter._response_data_or_none({"code": "0", "message": "not-success", "data": {"ok": 1}}) == {"ok": 1}
    assert adapter._response_data_or_none({"code": 0, "message": "not-success", "data": {"ok": 2}}) == {"ok": 2}
    assert adapter._response_data_or_none({"code": 1, "message": "SUCCESS", "data": {"ok": 3}}) == {"ok": 3}
    assert adapter._response_data_or_none({"code": 1, "message": "failed", "data": {"ok": 4}}) is None


def test_mteam_detail_payload_requires_id_field_name():
    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")

    payload = adapter.build_detail_payload("1172412")

    assert "id" in payload
    assert "tid" not in payload


def test_mteam_format_size_treats_raw_value_as_bytes():
    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")

    size = adapter._format_size("20895219507")

    assert size == "19.46 GB"


def test_is_download_url_torrent_validates_content_type(monkeypatch):
    class FakeResponse:
        def __init__(self, content_type: str, body: bytes):
            self.headers = {"content-type": content_type}
            self.content = body

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type
            _ = exc
            _ = tb
            return False

        def get(self, url: str):
            if "good" in url:
                return FakeResponse("application/x-bittorrent", b"d8:announce")
            return FakeResponse("application/json;charset=UTF-8", b'{"code":1,"message":"not found"}')

    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")
    monkeypatch.setattr(mteam_module.httpx, "Client", FakeClient)

    assert adapter.is_download_url_torrent("https://download.local/good") is True
    assert adapter.is_download_url_torrent("https://download.local/bad") is False
