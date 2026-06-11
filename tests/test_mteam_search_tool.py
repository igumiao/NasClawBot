from typing import Any

import pytest

from app.tools.mteam_search import MTeamSearchTool


class FakeMTeamAdapter:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[dict[str, Any]] = []

    def search_torrents_by_keyword(self, keyword: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"keyword": keyword, **kwargs})
        return self.rows


def test_mteam_search_schema_exposes_only_agreed_optional_parameters():
    schema = MTeamSearchTool(FakeMTeamAdapter()).to_openai_schema()["function"]["parameters"]

    assert schema["required"] == []
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"keyword", "sort_by", "imdb", "douban"}
    assert schema["properties"]["sort_by"]["enum"] == ["smallest", "largest", "most_seeded"]


@pytest.mark.parametrize(
    ("sort_by", "sort_field", "sort_direction"),
    [
        ("smallest", "SIZE", "ASC"),
        ("largest", "SIZE", "DESC"),
        ("most_seeded", "SEEDERS", "DESC"),
    ],
)
def test_mteam_search_maps_agent_sort_presets(sort_by: str, sort_field: str, sort_direction: str):
    adapter = FakeMTeamAdapter()
    tool = MTeamSearchTool(adapter)

    response = tool.run({"sort_by": sort_by})

    assert response.status.value == "success"
    assert adapter.calls[0]["sort_field"] == sort_field
    assert adapter.calls[0]["sort_direction"] == sort_direction


def test_mteam_search_uses_default_query_without_sort_fields():
    adapter = FakeMTeamAdapter()
    tool = MTeamSearchTool(adapter)

    response = tool.run({})

    assert response.status.value == "success"
    assert adapter.calls[0] == {
        "keyword": "",
        "page": 1,
        "page_size": 20,
        "mode": "normal",
        "sort_field": None,
        "sort_direction": None,
        "imdb": None,
        "douban": None,
    }
    assert response.data["applied_query"] == {}


def test_mteam_search_returns_at_most_ten_candidates_with_extra_status_fields():
    rows = [
        {
            "id": str(index),
            "title": f"Candidate {index}",
            "seeders": index,
            "leechers": index + 1,
            "discount": "PERCENT_50",
            "imdb": "tt1160419",
            "douban": "3001114",
            "size": "1.00 GB",
            "size_bytes": 1073741824,
        }
        for index in range(12)
    ]
    tool = MTeamSearchTool(FakeMTeamAdapter(rows))

    response = tool.run({})

    assert response.data["pool_count"] == 12
    assert response.data["returned_count"] == 12
    assert len(response.data["candidates"]) == 12
    assert response.data["candidates"][0]["media_type"] == "unknown"
    assert response.data["candidates"][0]["resolution"] is None
    assert response.data["candidates"][0]["leechers"] == 1
    assert response.data["candidates"][0]["discount"] == "PERCENT_50"


def test_mteam_search_prefers_small_description_for_resolution():
    tool = MTeamSearchTool(
        FakeMTeamAdapter(
            [
                {
                    "id": "1",
                    "title": "Dune 2021 2160p Blu-ray",
                    "name": "Dune 2021 2160p Blu-ray",
                    "small_description": "1080p @ 22998 kbps",
                    "size": "1.00 GB",
                    "size_bytes": 1073741824,
                }
            ]
        )
    )

    response = tool.run({"keyword": "Dune"})

    assert response.data["candidates"][0]["title"] == "Dune 2021 2160p Blu-ray"
    assert response.data["candidates"][0]["resolution"] == "1080p"


def test_mteam_search_does_not_guess_from_name_when_small_description_exists():
    tool = MTeamSearchTool(
        FakeMTeamAdapter(
            [
                {
                    "id": "1",
                    "title": "Dune 2021 2160p Blu-ray",
                    "name": "Dune 2021 2160p Blu-ray",
                    "small_description": "TrueHD 7.1 Atmos",
                    "size": "1.00 GB",
                    "size_bytes": 1073741824,
                }
            ]
        )
    )

    response = tool.run({"keyword": "Dune"})

    assert response.data["candidates"][0]["resolution"] is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Demo 4320p WEB-DL", "4320p"),
        ("Demo 8K WEB-DL", "4320p"),
        ("Demo 2160p WEB-DL", "2160p"),
        ("Demo 4K WEB-DL", "2160p"),
        ("Demo 1080p WEB-DL", "1080p"),
        ("Demo 720p WEB-DL", "720p"),
    ],
)
def test_mteam_search_falls_back_to_name_for_resolution(name: str, expected: str):
    tool = MTeamSearchTool(
        FakeMTeamAdapter(
            [
                {
                    "id": "1",
                    "title": name,
                    "name": name,
                    "small_description": None,
                    "size": "1.00 GB",
                    "size_bytes": 1073741824,
                }
            ]
        )
    )

    response = tool.run({"keyword": "Demo"})

    assert response.data["candidates"][0]["resolution"] == expected


@pytest.mark.parametrize(
    "parameters",
    [
        {"mode": "movie"},
        {"sort_by": "newest"},
        {"discount": "FREE"},
        None,
    ],
)
def test_mteam_search_rejects_unsupported_agent_parameters(parameters: dict[str, Any] | None):
    response = MTeamSearchTool(FakeMTeamAdapter()).run(parameters)

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"
