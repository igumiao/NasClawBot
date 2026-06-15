"""HTTP routes for memory inbox and curation."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    CuratorApplyRequest,
    CuratorApplyResponse,
    CurationResponse,
    CurationSections,
    MemoryInboxEntry,
    MemoryInboxResponse,
)
from app.domain.memory import MemoryKind
from app.services.curator import run_curation
from app.services.markdown_memory_store import MarkdownMemoryStore

_MEMORY_DIR = Path(__file__).resolve().parents[2] / "memory" / "agent-memory"


def _build_store() -> MarkdownMemoryStore:
    return MarkdownMemoryStore(_MEMORY_DIR)


def build_memory_router() -> APIRouter:
    router = APIRouter(prefix="/memory", tags=["memory"])

    @router.get("/inbox", response_model=MemoryInboxResponse)
    def get_inbox():
        store = _build_store()
        entries = store.parse_inbox()
        return MemoryInboxResponse(
            entries=[
                MemoryInboxEntry(
                    index=e["index"],
                    timestamp=str(e["timestamp"]),
                    text=str(e["text"]),
                )
                for e in entries
            ],
            entry_count=len(entries),
        )

    @router.post("/curate", response_model=CurationResponse)
    def curate():
        store = _build_store()
        try:
            result = run_curation(store)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Curator LLM call failed: {exc}")
        return CurationResponse(
            suggestions=[
                {
                    "inbox_index": s.inbox_index,
                    "preview": s.preview,
                    "action": s.action,
                    "destination": s.destination,
                    "section": s.section,
                    "edited_text": s.edited_text,
                }
                for s in result.suggestions
            ],
            inbox_entry_count=result.inbox_entry_count,
            sections=CurationSections(
                user_profile=store.get_sections(MemoryKind.USER_PROFILE),
                knowledge=store.get_sections(MemoryKind.KNOWLEDGE),
            ),
        )

    @router.patch("/curate/apply", response_model=CuratorApplyResponse)
    def apply_curation(request: CuratorApplyRequest):
        store = _build_store()
        entries = store.parse_inbox()
        if len(entries) != request.inbox_entry_count:
            raise HTTPException(
                status_code=409,
                detail=f"Inbox changed: expected {request.inbox_entry_count} entries, found {len(entries)}.",
            )

        applied = 0
        discarded = 0
        modified = 0
        deleted = 0
        processed: set[int] = set()
        kind_map = {
            "user_profile": MemoryKind.USER_PROFILE,
            "knowledge": MemoryKind.KNOWLEDGE,
        }

        for decision in request.decisions:
            processed.add(decision.inbox_index)
            if decision.action == "keep" and decision.destination and decision.text:
                store.append_to_section(
                    kind=kind_map[decision.destination],
                    section=decision.section or "Other",
                    text=decision.text,
                )
                applied += 1
            elif decision.action == "modify" and decision.destination and decision.existing_text and decision.new_text:
                store.replace_in_section(
                    kind=kind_map[decision.destination],
                    existing_text=decision.existing_text,
                    new_text=decision.new_text,
                )
                modified += 1
            elif decision.action == "delete" and decision.destination and decision.existing_text:
                store.delete_from_section(
                    kind=kind_map[decision.destination],
                    existing_text=decision.existing_text,
                )
                deleted += 1
            else:
                discarded += 1

        # Rebuild inbox from unprocessed entries
        remaining = [entries[i] for i in range(len(entries)) if i not in processed]
        inbox_path = _MEMORY_DIR / "memory_inbox.md"
        if remaining:
            blocks = []
            for entry in remaining:
                blocks.append(
                    f"## {entry['timestamp']} | 知识\n\n{entry['text']}\n\n---\n"
                )
            inbox_path.write_text("\n".join(blocks), encoding="utf-8")
        elif inbox_path.exists():
            inbox_path.write_text("", encoding="utf-8")

        return CuratorApplyResponse(
            applied=applied,
            discarded=discarded,
            modified=modified,
            deleted=deleted,
            remaining=len(remaining),
        )

    return router
