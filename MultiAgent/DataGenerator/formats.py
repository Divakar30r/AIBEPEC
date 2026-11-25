"""Value-format conversion for loading into drafts (Units).

Formats are the tokens XternalLoad's LLM writes into mapping.json as csv_format / db_format
(defined once in ../format_tokens.py). Values in a unit's draft are kept in
the db_format of their target field:

  * CSV values (source.py)                 csv_format -> db_format
  * LLM (A) conversions and UI input       auto-detected -> db_format   (generator.rerun_unit)

A value that cannot be converted is returned unchanged - rule validation then flags it.
JSON / JSONB formats are not handled yet.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from format_tokens import BOOLEAN, DATE_FORMATS, DB_TYPE_FORMATS, DECIMAL, INTEGER, TEXT  # noqa: E402,F401  (shared vocabulary)

_TRUE, _FALSE = {"true", "t", "yes", "y", "1"}, {"false", "f", "no", "n", "0"}


def norm(fmt: str | None) -> str | None:
    """Normalise a format from mapping.json to a known token, or None if it isn't one.

    Tolerates what LLMs tend to write: any case, 'date:%Y-%m-%d' / bare strptime patterns, 'currency (...)'.
    """
    if not fmt:
        return None
    f = str(fmt).strip()
    if ":" in f and f.split(":", 1)[0].lower() in ("date", "datetime"):
        f = f.split(":", 1)[1].strip()
    by_pattern = {p: tok for tok, p in DATE_FORMATS.items()}
    if f in by_pattern:
        return by_pattern[f]
    if f.upper() in DATE_FORMATS:
        return f.upper()
    low = f.lower()
    for group in (INTEGER, DECIMAL, TEXT, BOOLEAN):
        if low in group:
            return low
    if low.startswith("currency") or "#" in f:
        return "currency"
    if "unit" in low:
        return "number+unit"
    if low in ("json", "jsonb"):
        return "json"
    return None  # not a known token (e.g. 'Dates') - callers fall back to the DB column type


def is_date_format(fmt: str | None) -> bool:
    return norm(fmt) in DATE_FORMATS


def parse_date(value: Any, fmt: str | None = None) -> datetime | None:
    """Parse with the given token first, then every known token."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    order = ([DATE_FORMATS[norm(fmt)]] if is_date_format(fmt) else []) + list(DATE_FORMATS.values())
    for p in order:
        try:
            return datetime.strptime(s, p)
        except ValueError:
            continue
    return None


def _number(value: Any) -> float | None:
    """'₹151,678' / '1,200.50' / '1.5 LPA' / '42' -> float (units are dropped, not scaled)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    m = re.search(r"[+-]?\d[\d,]*(\.\d+)?", str(value))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def convert(value: Any, db_format: str | None, csv_format: str | None = None) -> Any:
    """Convert value to db_format. csv_format (optional) helps date parsing; otherwise auto-detect."""
    target = norm(db_format)
    if value is None or target is None:
        return value
    if isinstance(value, str) and value.strip() == "":
        return value
    if target in DATE_FORMATS:
        d = parse_date(value, csv_format)
        if d is None:
            return value
        return d.strftime(DATE_FORMATS[target])
    if target in INTEGER:
        n = _number(value)
        return int(round(n)) if n is not None else value
    if target in DECIMAL or target in ("currency", "number+unit"):
        n = _number(value)
        return n if n is not None else value
    if target in BOOLEAN:
        s = str(value).strip().lower()
        return True if s in _TRUE else False if s in _FALSE else value
    if target in TEXT:
        return str(value).strip()
    return value  # unknown / json formats: leave as is


def db_formats(mapping_entries: list[dict[str, Any]]) -> dict[str, str]:
    """target ('Table.Field') -> db_format, from mapping.json entries that state one."""
    return {e["target"]: norm(e["db_format"]) for e in mapping_entries
            if e.get("target") and norm(e.get("db_format"))}  # unknown tokens are dropped -> DB type applies


def formats_from_db_types(profile: dict[str, Any]) -> dict[str, str]:
    """target -> format token derived from the data DB column types (Schemafetcher.table_profile)."""
    out = {}
    for table, t in profile.items():
        for fld, info in t.get("columns", {}).items():
            tok = DB_TYPE_FORMATS.get(str(info.get("data_type", "")).lower())
            if tok:
                out[f"{table}.{fld}"] = tok
    return out
