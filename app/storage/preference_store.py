"""Persistence helpers for long-lived user preferences."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from app.storage.db import connect, ensure_schema


class PreferenceStore:
    """CRUD-style access to the `preferences` table."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_schema(self.db_path)

    def upsert(
        self,
        user_id: str,
        preferred_resolution: str | None = None,
        subtitle_preference: str | None = None,
        encoding_preference: str | None = None,
        default_download_profile: str | None = None,
    ) -> None:
        """Insert/update one user's preference profile."""
        with closing(connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO preferences (
                    user_id,
                    preferred_resolution,
                    subtitle_preference,
                    encoding_preference,
                    default_download_profile
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    preferred_resolution = excluded.preferred_resolution,
                    subtitle_preference = excluded.subtitle_preference,
                    encoding_preference = excluded.encoding_preference,
                    default_download_profile = excluded.default_download_profile,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    preferred_resolution,
                    subtitle_preference,
                    encoding_preference,
                    default_download_profile,
                ),
            )

    def get(self, user_id: str) -> dict[str, Any] | None:
        """Fetch stored preferences for one user id."""
        with closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT * FROM preferences WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None
