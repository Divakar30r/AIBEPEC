"""XLSource: a random sample of CSV rows reduced to the mapped columns (keyed 'Table.Field')."""
from __future__ import annotations

import csv
import json
import random
from typing import Any

from settings import Config


def load_mapping(cfg: Config) -> list[dict[str, Any]]:
    """Entries from the schema-matching run whose reason is 'Exact match' and that name a CSV column.

    Expected entry shape: {target, csv_column, confidence, reason}. No value_map / note / enabled.
    """
    entries = json.loads(cfg.mapping.read_text(encoding="utf-8"))["mappings"]
    return [e for e in entries
            if e.get("csv_column") and str(e.get("reason", "")).strip().lower() == "exact match"]


def load_xlsource(cfg: Config, rng: random.Random) -> list[dict[str, Any]]:
    mapping = load_mapping(cfg)
    with cfg.csv.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    sample = rng.sample(rows, min(cfg.source_rows, len(rows)))
    out: list[dict[str, Any]] = []
    for row in sample:
        rec: dict[str, Any] = {}
        for e in mapping:
            raw = row.get(e["csv_column"])
            if raw is None or raw.strip() == "":
                continue
            rec[e["target"]] = raw.strip()
        out.append(rec)
    return out
