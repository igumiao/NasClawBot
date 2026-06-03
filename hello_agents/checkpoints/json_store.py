"""JSON-backed conversation checkpoint storage."""

import json
import os
import re
from pathlib import Path

from .store import ConversationCheckpoint, ConversationCheckpointSummary


_SESSION_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


class JSONConversationCheckpointStore:
    """Persist checkpoints as one JSON file per stable session id."""

    def __init__(self, checkpoint_dir: str | Path):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def load(self, session_id: str) -> ConversationCheckpoint | None:
        path = self._path_for(session_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as file:
            return ConversationCheckpoint.from_dict(json.load(file))

    def save(self, checkpoint: ConversationCheckpoint) -> None:
        path = self._path_for(checkpoint.session_id)
        temp_path = Path(f"{path}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(checkpoint.to_dict(), file, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)

    def delete(self, session_id: str) -> bool:
        path = self._path_for(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list(self) -> list[ConversationCheckpointSummary]:
        summaries: list[ConversationCheckpointSummary] = []
        for path in self.checkpoint_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as file:
                    data = json.load(file)
            except (OSError, json.JSONDecodeError):
                continue
            summaries.append(
                ConversationCheckpointSummary(
                    session_id=str(data.get("session_id", path.stem)),
                    created_at=str(data.get("created_at", "")),
                    saved_at=str(data.get("saved_at", "")),
                    message_count=len(data.get("history", [])),
                    metadata=dict(data.get("metadata", {})),
                )
            )
        summaries.sort(key=lambda item: item.saved_at, reverse=True)
        return summaries

    def _path_for(self, session_id: str) -> Path:
        return self.checkpoint_dir / f"{self._safe_session_name(session_id)}.json"

    @staticmethod
    def _safe_session_name(session_id: str) -> str:
        cleaned = _SESSION_NAME_PATTERN.sub("-", session_id.strip())[:120].strip(".-")
        return cleaned or "default"
