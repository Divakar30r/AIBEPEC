"""Loads config.json (override the location with DATAGEN_CONFIG). Relative paths resolve against this folder."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    @property
    def parent(self) -> str:
        return next(t for t, c in self.tables.items() if c["role"] == "parent")

    @property
    def children(self) -> dict[str, dict[str, Any]]:
        return {t: c for t, c in self.tables.items() if c["role"] == "child"}


def load_config(path: str | Path | None = None, **overrides: Any) -> Config:
    path = Path(path or os.getenv("DATAGEN_CONFIG", HERE / "config.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update({k: v for k, v in overrides.items() if v is not None})
    p = raw["paths"]

    def res(rel: str) -> Path:
        return (HERE / rel).resolve()

    for t, c in raw["tables"].items():
        if c["role"] == "child" and not 1 <= c["min_per_key"] <= c["max_per_key"]:
            raise ValueError(f"{t}: need 1 <= min_per_key <= max_per_key")
    return Config(
        units=int(raw["units"]), workers=int(raw["workers"]), seed=raw.get("seed"),
        source_rows=int(raw.get("source_rows") or raw["units"]),
        key_field=raw["primary_key"]["field"], key_length=int(raw["primary_key"]["length"]),
        tables=raw["tables"], csv=res(p["csv"]), field_desc=res(p["field_desc"]),
        registry_dump=res(p["registry_dump"]), mapping=res(p["mapping"]), output_dir=res(p["output_dir"]),
        faker_locale=raw.get("faker_locale", "en_IN"), faker_default=raw.get("faker_default", "word"),
        faker=raw.get("faker", {}),
    )
