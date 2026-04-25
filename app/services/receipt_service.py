"""Helpers for building structured execution receipts."""


def build_receipt(
    resource_title: str,
    external_id: str,
    qb_category: str,
    qb_hash: str | None,
    status: str,
) -> dict[str, str | None]:
    """Return a stable receipt object for UI and API responses."""

    return {
        "resource_title": resource_title,
        "external_id": external_id,
        "qb_category": qb_category,
        "qb_hash": qb_hash,
        "status": status,
    }
