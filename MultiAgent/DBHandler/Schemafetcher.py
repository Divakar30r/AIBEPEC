"""Data-DB schema access (DATADB_* in DBHandler/.env).

  relations(field_tables)        parent/child tables and key columns from FOREIGN KEY constraints
  table_profile(field_tables)    per table: column data types + one sample row (first row, if any)
  write_sample_json(field_tables) writes the profile to DBHandler/sample_rows.json (generated on each
                                 match_schema run; tracked as a reference sample)

Table/column names are matched case-insensitively against the FieldDesc.MD names that callers
pass in (Postgres folds `PolMaster` to `polmaster`); output always uses the FieldDesc names.
Supported FK shape: one root table and any number of direct children (single-column FKs).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg

from db_config import DATA_DB, DataDBConfig

HERE = Path(__file__).resolve().parent
SAMPLE_JSON = HERE / "sample_rows.json"


class SchemaError(RuntimeError):
    """The data DB is unreachable or does not expose a usable foreign-key layout."""


@dataclass(frozen=True)
class ForeignKey:
    name: str
    child_table: str
    child_cols: tuple[str, ...]
    parent_table: str
    parent_cols: tuple[str, ...]


@dataclass(frozen=True)
class Child:
    key_field: str  # child column holding the parent key, as named in FieldDesc.MD
    fk_name: str
    parent_field: str


@dataclass(frozen=True)
class Relations:
    parent: str
    key_field: str  # the parent column the children reference
    children: dict[str, Child]
    db_name: str = ""


def _connect(cfg: DataDBConfig) -> psycopg.Connection:
    if not cfg.name:
        raise SchemaError("DATADB_NAME is not set (see DBHandler/.env.example)")
    try:
        return psycopg.connect(**cfg.connect_kwargs())
    except psycopg.Error as e:
        raise SchemaError(f"Cannot connect to data DB {cfg.name!r}: {e}") from e


# --------------------------------------------------------------------------- #
# Foreign keys -> relations
# --------------------------------------------------------------------------- #
_FK_SQL = """
SELECT c.conname, cl.relname, pcl.relname,
       (SELECT array_agg(a.attname ORDER BY k.ord)
          FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum),
       (SELECT array_agg(a.attname ORDER BY k.ord)
          FROM unnest(c.confkey) WITH ORDINALITY k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.attnum)
FROM pg_constraint c
JOIN pg_class cl  ON cl.oid  = c.conrelid
JOIN pg_class pcl ON pcl.oid = c.confrelid
JOIN pg_namespace n ON n.oid = cl.relnamespace
WHERE c.contype = 'f' AND n.nspname = %s
ORDER BY c.conname
"""


def read_foreign_keys(cfg: DataDBConfig = DATA_DB) -> list[ForeignKey]:
    try:
        with _connect(cfg) as conn:
            rows = conn.execute(_FK_SQL, (cfg.schema,)).fetchall()
    except psycopg.Error as e:
        raise SchemaError(f"Cannot read foreign keys from {cfg.name!r}: {e}") from e
    return [ForeignKey(n, c, tuple(cc), p, tuple(pc)) for n, c, p, cc, pc in rows]


def _field(fields: list[str], db_col: str) -> str:
    """Name used in FieldDesc.MD for a DB column (case-insensitive), else the DB name itself."""
    return next((f for f in fields if f.lower() == db_col.lower()), db_col)


def derive(fks: list[ForeignKey], field_tables: dict[str, list[str]], db_name: str = "") -> Relations:
    by_lower = {t.lower(): t for t in field_tables}
    links = [(fk, by_lower[fk.child_table.lower()], by_lower[fk.parent_table.lower()])
             for fk in fks if fk.child_table.lower() in by_lower and fk.parent_table.lower() in by_lower]
    if not links:
        raise SchemaError(f"No foreign key links the FieldDesc tables {sorted(field_tables)} to each other")
    roots = {p for _, _, p in links} - {c for _, c, _ in links}
    if len(roots) != 1:
        raise SchemaError(f"Expected exactly one root table, found {sorted(roots) or 'none'}")
    root = roots.pop()
    children: dict[str, Child] = {}
    for fk, c, p in links:
        if p != root:
            raise SchemaError(f"{c} -> {p}: only direct children of {root} are supported")
        if len(fk.child_cols) != 1:
            raise SchemaError(f"{fk.name}: composite foreign keys are not supported")
        if c in children:
            raise SchemaError(f"{c} has more than one foreign key to {root}")
        children[c] = Child(_field(field_tables[c], fk.child_cols[0]), fk.name,
                            _field(field_tables[root], fk.parent_cols[0]))
    parent_keys = {ch.parent_field for ch in children.values()}
    if len(parent_keys) != 1:
        raise SchemaError(f"Children reference different {root} columns: {sorted(parent_keys)}")
    return Relations(root, parent_keys.pop(), children, db_name)


@lru_cache(maxsize=8)
def _cached_relations(field_key: tuple) -> Relations:
    return derive(read_foreign_keys(DATA_DB), {t: list(fs) for t, fs in field_key}, DATA_DB.name)


def relations(field_tables: dict[str, list[str]]) -> Relations:
    """Cached per table list; call clear_cache() after the DB schema changes."""
    return _cached_relations(tuple(sorted((t, tuple(fs)) for t, fs in field_tables.items())))


def clear_cache() -> None:
    _cached_relations.cache_clear()


# --------------------------------------------------------------------------- #
# Column data types + sample row
# --------------------------------------------------------------------------- #
_COLS_SQL = """
SELECT table_name, column_name, data_type, character_maximum_length, numeric_precision, numeric_scale, is_nullable
FROM information_schema.columns WHERE table_schema = %s ORDER BY table_name, ordinal_position
"""


def _jsonable(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v if isinstance(v, (str, int, float, bool, dict, list, type(None))) else str(v)


def table_profile(field_tables: dict[str, list[str]], cfg: DataDBConfig = DATA_DB) -> dict[str, Any]:
    """{Table: {"db_table", "columns": {Field: {db_column, data_type, ...}}, "sample": {Field: value} | None}}.

    Only tables named in field_tables (FieldDesc.MD) are returned; columns keep the FieldDesc name
    when one matches, otherwise the DB name. The sample is the first row of the table, if any.
    """
    by_lower = {t.lower(): t for t in field_tables}
    out: dict[str, Any] = {}
    try:
        with _connect(cfg) as conn:
            for tbl, col, dtype, maxlen, prec, scale, nullable in conn.execute(_COLS_SQL, (cfg.schema,)).fetchall():
                name = by_lower.get(tbl.lower())
                if name is None:
                    continue
                t = out.setdefault(name, {"db_table": tbl, "columns": {}, "sample": None})
                info = {"db_column": col, "data_type": dtype, "nullable": nullable == "YES"}
                if maxlen:
                    info["max_length"] = maxlen
                if dtype == "numeric" and prec:
                    info["precision"], info["scale"] = prec, scale
                t["columns"][_field(field_tables[name], col)] = info
            for name, t in out.items():
                cur = conn.execute(psycopg.sql.SQL("SELECT * FROM {}.{} LIMIT 1").format(
                    psycopg.sql.Identifier(cfg.schema), psycopg.sql.Identifier(t["db_table"])))
                row = cur.fetchone()
                if row is not None:
                    cols = [d.name for d in cur.description]
                    t["sample"] = {_field(field_tables[name], c): _jsonable(v) for c, v in zip(cols, row)}
    except psycopg.Error as e:
        raise SchemaError(f"Cannot read columns/sample from {cfg.name!r}: {e}") from e
    return out


def write_sample_json(field_tables: dict[str, list[str]], path: Path = SAMPLE_JSON) -> Path:
    """Write table_profile() to sample_rows.json - the 'sample row data' shared by XternalLoad and DataGenerator."""
    prof = table_profile(field_tables)
    path.write_text(json.dumps({"_comment": "GENERATED by DBHandler/Schemafetcher.write_sample_json() on every "
                                            "XternalLoad/match_schema.py run - do not edit by hand; it is overwritten on each run.",
                                "database": DATA_DB.name, "schema": DATA_DB.schema, "tables": prof},
                               indent=2, default=str), encoding="utf-8")
    return path
