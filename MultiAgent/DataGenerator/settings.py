"""Loads config.json (override the location with DATAGEN_CONFIG). Relative paths resolve against this folder."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "DBHandler"))
import Schemafetcher  # noqa: E402  (DBHandler: the only DB client)

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Config:
    units: int
    workers: int
    seed: int | None
    source_rows: int
    key_field: str
    key_length: int
    tables: dict[str, dict[str, Any]]
    csv: Path
    field_desc: Path
    registry_dump: Path
    mapping: Path
    output_dir: Path
    faker_locale: str
    faker_default: str
    faker: dict[str, str]
    db_name: str = ""
    count_dump: Path | None = None
    llm_review: bool = True  # auto-run ../LLMEffects/review.py when units need review

    @property
    def parent(self) -> str:
        return next(t for t, c in self.tables.items() if c["role"] == "parent")

    @property
    def children(self) -> dict[str, dict[str, Any]]:
        return {t: c for t, c in self.tables.items() if c["role"] == "child"}


def load_config(path: str | Path | None = None, per_key: dict[str, tuple[int, int]] | None = None,
                **overrides: Any) -> Config:
    """per_key: {child_table: (min, max)} overrides the config.json defaults (e.g. from the UI)."""
    path = Path(path or os.getenv("DATAGEN_CONFIG", HERE / "config.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update({k: v for k, v in overrides.items() if v is not None})
    p = raw["paths"]

    def res(rel: str) -> Path:
        return (HERE / rel).resolve()

    from schema import parse_field_desc  # lazy: schema imports this module
    field_desc = res(p["field_desc"])
    fields = parse_field_desc(field_desc.read_text(encoding="utf-8"))
    rel = Schemafetcher.relations(fields)  # data DB settings: DBHandler/.env (DATADB_*)
    db_name = rel.db_name

    defaults = raw.get("per_key", {})
    tables: dict[str, dict[str, Any]] = {rel.parent: {"role": "parent"}}
    for t, ch in rel.children.items():
        lim = {"min": 1, "max": 1, **defaults.get("default", {}), **defaults.get(t, {})}
        if per_key and t in per_key:
            lim["min"], lim["max"] = per_key[t]
        if not 1 <= int(lim["min"]) <= int(lim["max"]):
            raise ValueError(f"{t}: need 1 <= min_per_key <= max_per_key (got {lim['min']}..{lim['max']})")
        tables[t] = {"role": "child", "key_field": ch.key_field, "min_per_key": int(lim["min"]),
                     "max_per_key": int(lim["max"]), "fk": ch.fk_name}
    return Config(
        units=int(raw["units"]), workers=int(raw["workers"]), seed=raw.get("seed"),
        source_rows=int(raw.get("source_rows") or raw["units"]),
        key_field=rel.key_field, key_length=int(raw["primary_key"]["length"]),
        tables=tables, csv=res(p["csv"]), field_desc=field_desc,
        registry_dump=res(p["registry_dump"]), mapping=res(p["mapping"]), output_dir=res(p["output_dir"]),
        faker_locale=raw.get("faker_locale", "en_IN"), faker_default=raw.get("faker_default", "word"),
        faker=raw.get("faker", {}), db_name=db_name,
        count_dump=res(p["count_dump"]) if p.get("count_dump") else None,
        llm_review=bool(raw.get("llm_review", True)),
    )
