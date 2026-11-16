"""Detect PostgreSQL types from the values of a JSON sample, in code rather than by the LLM.

JSON types map directly (bool -> boolean, int -> integer/bigint, float -> numeric, object ->
jsonb, array -> <element>[]), and strings are inspected: "12" is an integer, "true" a boolean,
"2025-01-31" a date, and so on.
"""

import json
import re
from datetime import date, datetime

from .BackendConstants import BOOL_STRINGS

_INT = re.compile(r"[+-]?(0|[1-9]\d*)")
_NUMERIC = re.compile(r"[+-]?(\d+\.\d+|\.\d+)")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME = re.compile(r"\d{2}:\d{2}(:\d{2}(\.\d+)?)?")

NULL_TYPE = "unknown (null sample)"


def _int_type(number: int) -> str:
    if -(2**31) <= number < 2**31:
        return "integer"
    return "bigint" if -(2**63) <= number < 2**63 else "numeric"


def _string_type(text: str) -> str:
    s = text.strip()
    if s.lower() in BOOL_STRINGS:
        return "boolean"
    if _INT.fullmatch(s):
        return _int_type(int(s))
    if _NUMERIC.fullmatch(s):
        return "numeric"
    if _UUID.fullmatch(s):
        return "uuid"
    if _DATE.fullmatch(s):
        try:
            date.fromisoformat(s)
            return "date"
        except ValueError:
            return "text"
    if _TIME.fullmatch(s):
        return "time"
    if len(s) >= 16 and s[10] in "T " and _DATE.fullmatch(s[:10]):
        try:
            parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return "text"
        return "timestamptz" if parsed.tzinfo else "timestamp"
    return "text"


def infer_type(value) -> str:
    """PostgreSQL type suggested by one sample value."""
    if value is None:
        return NULL_TYPE
    if isinstance(value, bool):  # before int: bool is an int subclass
        return "boolean"
    if isinstance(value, int):
        return _int_type(value)
    if isinstance(value, float):
        return "numeric"
    if isinstance(value, dict):
        return "jsonb"
    if isinstance(value, list):
        element = next((v for v in value if v is not None), None)
        inner = "jsonb" if element is None else infer_type(element)
        return f"{inner}[]"
    return _string_type(str(value))


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 40 else text[:37] + "..."


def describe_sample(sample: str) -> str:
    """One line per field: ``- field: detected type (sample: value)``."""
    return "\n".join(
        f"- {field}: {infer_type(value)} (sample: {_short(value)})"
        for field, value in json.loads(sample).items()
    )


def describe_changes(sample: str, column_types: dict[str, str]) -> str:
    """For a partial sample of an existing table: which fields are new, which exist and how.

    ``column_types`` maps lower-cased column names to their current type.
    """
    lines = []
    for field, value in json.loads(sample).items():
        detected, current = infer_type(value), column_types.get(field.lower())
        if current is None:
            lines.append(f"- {field}: NEW column, detected type {detected} (sample: {_short(value)})")
        else:
            lines.append(
                f"- {field}: existing column of type {current}; sample suggests {detected} "
                f"(sample: {_short(value)})"
            )
    return "\n".join(lines)
