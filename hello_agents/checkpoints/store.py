"""Thin checkpoint abstractions for durable conversation state."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ConversationCheckpoint:
    """Persisted state needed to resume a conversation thread."""

    session_id: str
    created_at: str
    saved_at: str
    history: list[dict[str, Any]]
    archives: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "saved_at": self.saved_at,
            "history": self.history,
            "archives": self.archives,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationCheckpoint":
        return cls(
            session_id=str(data["session_id"]),
            created_at=str(data["created_at"]),
            saved_at=str(data["saved_at"]),
            history=list(data.get("history", [])),
            archives=list(data.get("archives", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ConversationCheckpointSummary:
    """Small row for session listing without loading full history."""

    session_id: str
    created_at: str
    saved_at: str
    message_count: int
    archive_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationCheckpointStore(Protocol):
    """Storage boundary for cross-request conversation checkpoints."""

    def load(self, session_id: str) -> ConversationCheckpoint | None:
        """Return the checkpoint for a session, if it exists."""

    def save(self, checkpoint: ConversationCheckpoint) -> None:
        """Persist a complete checkpoint."""

    def delete(self, session_id: str) -> bool:
        """Delete a checkpoint by stable session id."""

    def list(self) -> list[ConversationCheckpointSummary]:
        """List known checkpoints, most recently saved first."""
