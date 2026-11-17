"""Column types for the fields of a JSON sample, decided by the LLM for the configured database.

All fields go to the model in ONE call (``type-detection`` prompt) and come back as one JSON
object, so there is no per-field call and no hardcoded, database-specific pattern matching: the
target dialect (``settings.db_dialect``: PostgreSQL, MySQL, ...) is a prompt variable.
"""

import json

from .config import settings
from .llm import ask
from .Util import parse_json_object

UNKNOWN_TYPE = "unknown"


def detect_types(sample: str) -> dict[str, str]:
    """Field name -> column type for ``settings.db_dialect``, from a single LLM call.

    A field the model left out (or answered with an empty type) maps to ``unknown``; the model's
    key case is forgiven.
    """
    fields = json.loads(sample)
    reply = parse_json_object(ask("type-detection", dialect=settings.db_dialect, json_sample=sample))
    reply = reply or {}
    by_lower = {str(k).lower(): v for k, v in reply.items()}
    return {
        field: str(reply.get(field) or by_lower.get(field.lower()) or UNKNOWN_TYPE)
        for field in fields
    }


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 40 else text[:37] + "..."


def describe_sample(sample: str) -> str:
    """One line per field: ``- field: detected type (sample: value)``."""
    types = detect_types(sample)
    return "\n".join(
        f"- {field}: {types[field]} (sample: {_short(value)})"
        for field, value in json.loads(sample).items()
    )


def describe_changes(sample: str, column_types: dict[str, str]) -> str:
    """For a partial sample of an existing table: which fields are new, which exist and how.

    ``column_types`` maps lower-cased column names to their current type.
    """
    types = detect_types(sample)
    lines = []
    for field, value in json.loads(sample).items():
        detected, current = types[field], column_types.get(field.lower())
        if current is None:
            lines.append(f"- {field}: NEW column, detected type {detected} (sample: {_short(value)})")
        else:
            lines.append(
                f"- {field}: existing column of type {current}; sample suggests {detected} "
                f"(sample: {_short(value)})"
            )
    return "\n".join(lines)
