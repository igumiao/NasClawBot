"""Shared qB-to-local filesystem path mapping helpers."""

from __future__ import annotations


def parse_path_mapping(raw: str) -> dict[str, str]:
    """Parse comma-separated ``source->destination`` prefix mappings."""

    mapping: dict[str, str] = {}
    for pair in str(raw or "").split(","):
        pair = pair.strip()
        if not pair or "->" not in pair:
            continue
        source, destination = (part.strip() for part in pair.split("->", 1))
        if source and destination:
            mapping[source] = destination
    return mapping


def translate_path(path: str, mapping: dict[str, str] | None) -> str:
    """Translate a qB path prefix and normalize separators for local access."""

    value = str(path or "")
    if not value or not mapping:
        return value

    for source in sorted(mapping, key=len, reverse=True):
        windows_prefix = len(source) >= 2 and source[1] == ":"
        matches = (
            value.casefold().startswith(source.casefold())
            if windows_prefix
            else value.startswith(source)
        )
        if not matches:
            continue
        destination = mapping[source]
        remainder = value[len(source):].lstrip("/\\")
        translated = destination.rstrip("/\\")
        if remainder:
            translated = f"{translated}/{remainder}"
        return translated.replace("\\", "/")
    return value
