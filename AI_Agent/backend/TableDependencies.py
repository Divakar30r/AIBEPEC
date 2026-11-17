"""Node C1: pull an existing table and everything depending on it into the context."""

import re
from dataclasses import dataclass, field

from .BackendConstants import MESSAGES
from .config import settings
from .db import connect_target

_FIND_TABLE = """
SELECT c.oid, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND lower(c.relname) = lower(%s) AND c.relkind IN ('r', 'p')
"""

_COLUMNS = """
SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
       pg_get_expr(d.adbin, d.adrelid)
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
"""

# Constraints of the table plus foreign keys of other tables pointing at it, same schema only.
_CONSTRAINTS = """
SELECT c.contype, c.conname, c.conrelid = %(oid)s AS own, cl.relname, pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_class cl ON cl.oid = c.conrelid
JOIN pg_namespace cn ON cn.oid = cl.relnamespace
LEFT JOIN pg_class pl ON pl.oid = c.confrelid
LEFT JOIN pg_namespace pn ON pn.oid = pl.relnamespace
WHERE (c.conrelid = %(oid)s OR c.confrelid = %(oid)s)
  AND cn.nspname = %(schema)s AND (pn.nspname IS NULL OR pn.nspname = %(schema)s)
ORDER BY c.contype, c.conname
"""

_INDEXES = "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = %s"


_PLAIN_IDENT = re.compile(r"[a-z_][a-z0-9_$]*")


def quote_ident(name: str) -> str:
    """The name as it must be written in SQL: quoted unless it is plain lower case."""
    return name if _PLAIN_IDENT.fullmatch(name) else '"' + name.replace('"', '""') + '"'


@dataclass
class TableInfo:
    schema: str
    name: str
    columns: list[str] = field(default_factory=list)
    column_types: dict[str, str] = field(default_factory=dict)  # lower-cased name -> type
    constraints: list[str] = field(default_factory=list)  # PK, unique, check, own foreign keys
    referenced_by: list[str] = field(default_factory=list)  # foreign keys of other tables
    indexes: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Plain-text description handed to the LLM."""

        def block(title: str, lines: list[str]) -> str:
            return f"{title}:\n" + ("\n".join(f"  - {x}" for x in lines) if lines else "  (none)")

        return "\n\n".join(
            [
                f"Table {self.schema}.{quote_ident(self.name)}",
                block("Columns", self.columns),
                block("Constraints", self.constraints),
                block("Indexes", self.indexes),
                block("Referenced by (foreign keys of other tables)", self.referenced_by),
            ]
        )


def lookup_table(table_name: str, schema: str | None = None) -> tuple[int, str] | None:
    """(oid, real name) of the table (matched case-insensitively), None when it does not exist."""
    schema = schema or settings.target_schema
    with connect_target() as conn:
        found = conn.execute(_FIND_TABLE, (schema, table_name)).fetchone()
    return (found[0], found[1]) if found else None


def read_table_info(oid: int, name: str, schema: str | None = None) -> TableInfo:
    """Columns, constraints, referencing foreign keys and indexes of a table found by lookup."""
    schema = schema or settings.target_schema
    with connect_target() as conn:
        info = TableInfo(schema=schema, name=name)

        for col, col_type, not_null, default in conn.execute(_COLUMNS, (oid,)):
            parts = [f"{col} {col_type}"]
            if not_null:
                parts.append("NOT NULL")
            if default:
                parts.append(f"DEFAULT {default}")
            info.columns.append(" ".join(parts))
            info.column_types[col.lower()] = col_type

        for _contype, conname, own, relname, definition in conn.execute(
            _CONSTRAINTS, {"oid": oid, "schema": schema}
        ):
            if own:
                info.constraints.append(f"{conname}: {definition}")
            else:
                info.referenced_by.append(f"{relname}.{conname}: {definition}")

        info.indexes = [row[0] for row in conn.execute(_INDEXES, (schema, name))]
    return info


def fetch_table_info(table_name: str, schema: str | None = None) -> TableInfo | None:
    """Both steps in one call (C1A then C1B); None when the table does not exist."""
    found = lookup_table(table_name, schema)
    return read_table_info(*found, schema) if found else None


def table_names(primary: str, related: list[str]) -> list[str]:
    """The table to change first, then the related tables other than that one."""
    return [primary, *(t for t in related if t.lower() != primary.lower())]


def table_not_found_message(tables: list[str]) -> str:
    return MESSAGES["table_not_found"].format(
        tables=", ".join(f"`{t}`" for t in tables),
        schema=settings.target_schema,
        db=settings.pg_target_db,
    )
