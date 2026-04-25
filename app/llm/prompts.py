"""Prompt snippets for lightweight intent extraction.

Task 6 keeps this intentionally minimal while preserving a stable interface for
later replacement with real prompt templates.
"""

EXTRACT_CONSTRAINTS_SYSTEM_PROMPT = (
    "Extract media-search constraints from a user request and return JSON."
)


def build_extract_constraints_user_prompt(message: str) -> str:
    """Build the user-facing extraction prompt text."""

    return f"User request:\n{message}\n\nReturn normalized constraints."
