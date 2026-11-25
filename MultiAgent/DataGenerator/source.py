"""XLSource: a random sample of CSV rows reduced to the mapped columns (keyed 'Table.Field')."""
from __future__ import annotations

import csv
import json
import random
from functools import lru_cache
from typing import Any

import formats
from settings import Config


def load_mapping(cfg: Config) -> list[dict[str, Any]]:
    """Entries from the schema-matching run whose reason is 'Exact match' and that name a CSV column.

    Entry shape: {target, csv_column, confidence, reason, csv_format, db_format}; the formats are optional.
    """
    entries = json.loads(cfg.mapping.read_text(encoding="utf-8"))["mappings"]
    return [e for e in entries
            if e.get("csv_column") and str(e.get("reason", "")).strip().lower() == "exact match"]


@lru_cache(maxsize=4)
def _db_type_formats(field_desc: str) -> dict[str, str]:
    """target -> token from the data DB column types (via DBHandler); {} if the DB is unavailable."""
    import Schemafetcher  # DBHandler (path added by settings)
    from schema import parse_field_desc
    try:
        return formats.formats_from_db_types(Schemafetcher.table_profile(parse_field_desc(field_desc)))
    except Schemafetcher.SchemaError:
        return {}


def load_db_formats(cfg: Config) -> dict[str, str]:
    """target -> format every value of that field is stored in inside the units (the DB type).

    The data DB column type wins; mapping.json's db_format (from the LLM) only fills fields the DB
    doesn't describe directly (e.g. values inside JSON columns) or when the DB is unavailable.
    """
    out: dict[str, str] = {}
    try:
        out.update(formats.db_formats(json.loads(cfg.mapping.read_text(encoding="utf-8"))["mappings"]))
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    out.update(_db_type_formats(cfg.field_desc.read_text(encoding="utf-8")))
    return out


def load_xlsource(cfg: Config, rng: random.Random) -> list[dict[str, Any]]:
    mapping = load_mapping(cfg)
    with cfg.csv.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    sample = rng.sample(rows, min(cfg.source_rows, len(rows)))
    dbf = load_db_formats(cfg)  # DB column type wins over the LLM's db_format (e.g. smallint, not 'number')
    out: list[dict[str, Any]] = []
    for row in sample:
        rec: dict[str, Any] = {}
        for e in mapping:
            raw = row.get(e["csv_column"])
            if raw is None or raw.strip() == "":
                continue
            # Keep values in the target's DB format inside the units.
            rec[e["target"]] = formats.convert(raw.strip(), dbf.get(e["target"]) or e.get("db_format"),
                                               e.get("csv_format"))
        out.append(rec)
    return out
