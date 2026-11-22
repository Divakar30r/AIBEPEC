"""Prompt templates. Kept separate from code; the LLM call is stateless (no history)."""

SCHEMA_MATCH_SYSTEM = """You are a data-integration analyst. You compare the columns of an \
external CSV file with the target schema of an internal system and decide how they map. \
Use only the evidence given. Never invent columns or fields. If unsure, say so."""

SCHEMA_MATCH_USER = """TARGET SCHEMA (internal field descriptions):
{field_desc}

EXTERNAL CSV COLUMN PROFILES (retrieved context; values may be redacted):
{column_context}

ALL COLUMN NAMES IN THE CSV:
{column_names}

TASK:
1. For every target field above (written as <Table>.<Field>), name the CSV column that best \
matches it, or null when no column fits.
2. List CSV columns that match no target field.
3. Note data-quality issues visible in the profiles that would block loading (inconsistent \
category spellings, currency symbols or thousand separators in numbers, mixed formats, nulls).

Respond with JSON only, in exactly this shape:
{{
  "mappings": [
    {{"target": "<Table>.<Field>", "csv_column": "<column name> or null",
      "confidence": "high|medium|low", "reason": "short"}}
  ],
  "unmapped_csv_columns": ["..."],
  "data_quality_issues": [{{"column": "...", "issue": "..."}}]
}}"""
