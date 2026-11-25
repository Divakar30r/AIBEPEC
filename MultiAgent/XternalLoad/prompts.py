"""Prompt templates. Kept separate from code; the LLM call is stateless (no history)."""

SCHEMA_MATCH_SYSTEM = """You are a data-integration analyst. You compare the columns of an \
external CSV file with the target schema of an internal system and decide how they map. \
Use only the evidence given. Never invent columns or fields. If unsure, say so."""

# Format tokens: single source of truth in ../format_tokens.py (shared with DataGenerator / DAGRegistry).
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from format_tokens import PROMPT_TEXT as FORMAT_TOKENS  # noqa: E402

SCHEMA_MATCH_USER = """TARGET SCHEMA (internal field descriptions):
{field_desc}

TARGET DATABASE (column: data type, and a sample value when the table has data):
{db_schema}

EXTERNAL CSV COLUMN PROFILES (retrieved context; values may be redacted):
{column_context}

ALL COLUMN NAMES IN THE CSV:
{column_names}

FORMAT TOKENS (use exactly these words):
{format_tokens}

TASK:
1. For every target field above (written as <Table>.<Field>), name the CSV column that best \
matches it, or null when no column fits. Match first on the CSV column name against the \
field / database column name, then confirm with the profiles. Use the reason "Exact match" only \
when both clearly describe the same data.
2. For every mapping with a csv_column, give:
   - csv_format: how the values are written in the CSV (from the profile: shapes, date formats, \
encodings). If the column mixes formats, give the dominant one.
   - db_format: how the value must be written for the target database column (from its data type \
and the sample row). Use a format token.
   Use null for both when there is no csv_column.
3. List CSV columns that match no target field.
4. Note data-quality issues visible in the profiles that would block loading (mixed types, case \
variants, currency symbols or thousand separators in numbers, several date formats, nulls).

Respond with JSON only, in exactly this shape:
{{
  "mappings": [
    {{"target": "<Table>.<Field>", "csv_column": "<column name> or null",
      "confidence": "high|medium|low", "reason": "short",
      "csv_format": "<format token> or null", "db_format": "<format token> or null"}}
  ],
  "unmapped_csv_columns": ["..."],
  "data_quality_issues": [{{"column": "...", "issue": "..."}}]
}}"""
