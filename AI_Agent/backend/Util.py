"""Miscellaneous helpers: chat messages, and pulling JSON and SQL out of chat text."""

import json
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from .BackendConstants import SQL_FENCE_LANGS
from .config import settings

_FENCE = re.compile(r"```[ \t]*([A-Za-z]*)[ \t]*\n(.*?)```", re.DOTALL)
_decoder = json.JSONDecoder()


def to_messages(history: list[dict[str, str]]) -> list[BaseMessage]:
    """The last ``settings.history_messages`` chat dicts (``role``, ``content``) as messages."""
    recent = history[-settings.history_messages :] if settings.history_messages > 0 else []
    return [
        (HumanMessage if m["role"] == "user" else AIMessage)(content=m["content"]) for m in recent
    ]


def _first_json(text: str, kinds: tuple[type, ...]):
    """First JSON value of one of ``kinds`` found anywhere in ``text``, or None."""
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                value, _ = _decoder.raw_decode(text, i)
            except ValueError:
                continue
            if isinstance(value, kinds) and value:
                return value
    return None


def parse_json_object(text: str) -> dict | None:
    """First JSON object in ``text`` (LLM replies often wrap JSON in prose or fences)."""
    value = _first_json(text, (dict,))
    return value if isinstance(value, dict) else None


def find_json_sample(messages: list[BaseMessage]) -> str:
    """Most recent JSON sample (object or non-empty list) the user pasted, pretty-printed.

    Searches the human messages newest first, so a sample given earlier in the chat still counts.
    Returns '' when there is none.
    """
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and isinstance(message.content, str):
            value = _first_json(message.content, (dict, list))
            if value is not None:
                return json.dumps(value, indent=2)
    return ""


def is_valid_sample(sample: str) -> bool:
    """True when the JSON sample is one non-empty object of ``field name -> sample value``.

    Values may be any JSON type (string, number, boolean, null, object, array); their SQL types
    are detected in SampleTypes. A list of records or a bare value is invalid.
    """
    try:
        value = json.loads(sample)
    except ValueError:
        return False
    return isinstance(value, dict) and bool(value)


def extract_sql(text: str) -> str:
    """SQL from the fenced code blocks of an LLM reply (all of them, joined); else the text."""
    blocks = [
        body.strip()
        for lang, body in _FENCE.findall(text)
        if lang.lower() in SQL_FENCE_LANGS or not lang
    ]
    return "\n\n".join(b for b in blocks if b) if blocks else text.strip()
