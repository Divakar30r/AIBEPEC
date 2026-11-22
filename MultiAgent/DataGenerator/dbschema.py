"""Parent/child tables and key columns, derived from the database's FOREIGN KEY constraints.

Only tables that appear in FieldDesc.MD are considered. Names are matched case-insensitively
(Postgres folds `PolMaster` to `polmaster`). Supported shape: one root table and any number of
child tables, each with a single-column FK straight to the root.

Connection settings come from the environment (PG_HOST, PG_PORT, PG_USER, PG_PASSWORD), read from
DataGenerator/.env first, then XternalLoad/.env. The database name comes from config.json
("database.name") and can be overridden with DATAGEN_PG_DB.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import psycopg
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
for _env in (HERE / ".env", HERE.parent / "XternalLoad" / ".env"):  # load_dotenv never overrides, so first wins
    load_dotenv(_env)


class SchemaError(RuntimeError):
    """The database does not expose a foreign-key layout the generator can use."""


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


def read_foreign_keys(db_name: str, schema: str = "public") -> list[ForeignKey]:
    try:
        with psycopg.connect(dbname=db_name, host=os.getenv("PG_HOST", "localhost"),
                             port=int(os.getenv("PG_PORT", "5432")), user=os.getenv("PG_USER", "postgres"),
                             password=os.getenv("PG_PASSWORD", ""), connect_timeout=5) as conn:
            rows = conn.execute(_FK_SQL, (schema,)).fetchall()
    except psycopg.Error as e:
        raise SchemaError(f"Cannot read foreign keys from database {db_name!r}: {e}") from e
    return [ForeignKey(n, c, tuple(cc), p, tuple(pc)) for n, c, p, cc, pc in rows]


def _field(fields: list[str], db_col: str) -> str:
    """Name used in FieldDesc.MD for a DB column (case-insensitive), else the DB name itself."""
    return next((f for f in fields if f.lower() == db_col.lower()), db_col)


def derive(fks: list[ForeignKey], field_tables: dict[str, list[str]]) -> Relations:
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
    return Relations(root, parent_keys.pop(), children)


@lru_cache(maxsize=8)
def _cached(db_name: str, schema: str, field_key: tuple) -> Relations:
    return derive(read_foreign_keys(db_name, schema), {t: list(fs) for t, fs in field_key})


def relations(db_name: str, schema: str, field_tables: dict[str, list[str]]) -> Relations:
    """Cached per (database, schema, table list); call clear_cache() after the DB schema changes."""
    return _cached(db_name, schema, tuple(sorted((t, tuple(fs)) for t, fs in field_tables.items())))


def clear_cache() -> None:
    _cached.cache_clear()
