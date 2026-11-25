"""Shared value-format vocabulary for all MultiAgent folders (single source of truth).

  * XternalLoad  - PROMPT_TEXT tells the schema-matching LLM which tokens to use for csv_format / db_format
  * DataGenerator- DATE_FORMATS etc. drive conversion of values into the target's DB format
  * DAGRegistry  - DATE_FORMATS lets date rules read a date in any of these formats (rules check boundaries,
                   never the format)
  * DB_TYPE_FORMATS maps Postgres column data types to the token used when mapping.json has no db_format
"""
from __future__ import annotations

# Date tokens -> strptime / strftime patterns
DATE_FORMATS: dict[str, str] = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYYMMDD": "%Y%m%d",
    "YYYYMM": "%Y%m",
    "DD/MM/YYYY": "%d/%m/%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
    "DD.MM.YYYY": "%d.%m.%Y",
    "DD-MON-YYYY": "%d-%b-%Y",
    "YYYY-MM-DDTHH:MI:SS": "%Y-%m-%dT%H:%M:%S",
    "YYYY-MM-DD HH:MI:SS": "%Y-%m-%d %H:%M:%S",
}
INTEGER = frozenset({"integer", "int", "bigint", "smallint"})
DECIMAL = frozenset({"decimal", "numeric", "number", "float", "double", "real"})
TEXT = frozenset({"text", "string", "varchar"})
BOOLEAN = frozenset({"boolean", "bool"})
CURRENCY = "currency"
NUMBER_UNIT = "number+unit"
JSON = "json"

# Postgres information_schema.columns.data_type -> token
DB_TYPE_FORMATS: dict[str, str] = {
    "date": "YYYY-MM-DD",
    "timestamp without time zone": "YYYY-MM-DD HH:MI:SS",
    "timestamp with time zone": "YYYY-MM-DD HH:MI:SS",
    "smallint": "integer", "integer": "integer", "bigint": "integer",
    "numeric": "decimal", "real": "decimal", "double precision": "decimal",
    "text": "text", "character varying": "text", "character": "text", "uuid": "text",
    "boolean": "boolean",
    "json": JSON, "jsonb": JSON,
}

PROMPT_TEXT = (
    "Dates: " + ", ".join(DATE_FORMATS) + "\n"
    "Numbers: integer, decimal, currency (symbol and/or thousands separators, e.g. ₹#,##0), "
    "number+unit (e.g. 1.5 LPA)\n"
    "Other: text, boolean, json"
)
