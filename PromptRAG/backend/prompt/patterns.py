"""Prompt patterns the user can attach to a question. Their text lives in PromptTemplates."""

from .PromptTemplates import PATTERN_NAMES

PATTERNS: list[str] = list(PATTERN_NAMES)


def list_patterns() -> list[str]:
    return list(PATTERNS)
