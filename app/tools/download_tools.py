"""Deterministic helpers for preparing placeholder download execution data."""

from typing import Any


def prepare_download_execution(selected_result: dict[str, Any]) -> dict[str, str]:
    """Normalize the minimum fields required for Task 7 execution stubs."""

    return {
        "external_id": str(selected_result["id"]),
        "resource_title": str(selected_result["title"]),
    }
