"""Match CSV columns (from the vector DB) to the target schema (FieldDesc.MD + data DB) using an LLM.

1. Retrieve the nearest CSV column-profile chunks for each FieldDesc field line.
2. Fetch the data DB's column types and a sample row (DBHandler.Schemafetcher -> sample_rows.json).
3. One stateless LLM call: match CSV columns to target fields (by name first), and state the value
   format on each side (csv_format / db_format) so DataGenerator can convert while loading.
Writes mapping.json (read by DataGenerator).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import embedder
import llm
import prompts
from config import HERE, settings

sys.path.insert(0, str(HERE.parent / "DBHandler"))
import Schemafetcher  # noqa: E402  (DBHandler: the only DB client)
import vector_store  # noqa: E402

OUTPUT_PATH = HERE / "mapping.json"


def target_fields(text: str) -> list[str]:
    """Lines like `"FieldName": description` -> one retrieval query each."""
    return [m.group(0).strip().rstrip(",") for m in re.finditer(r'^\s*"[A-Za-z]+"\s*:.*$', text, re.M)]


def field_tables(text: str) -> dict[str, list[str]]:
    """'# Table' headings and their top-level '"Field":' names from FieldDesc.MD."""
    tables: dict[str, list[str]] = {}
    cur = None
    for line in text.splitlines():
        if m := re.match(r"^#+\s*(\w+)\s*$", line.strip()):
            cur = m.group(1)
            tables[cur] = []
        elif cur and (m := re.match(r'^\s*"(\w+)"\s*:', line)):
            tables[cur].append(m.group(1))
    return tables


def db_schema_context(text: str) -> str:
    """Data DB column types + sample row, compact (one line per column) to keep the prompt small.
    The full JSON is still written to DBHandler/sample_rows.json."""
    try:
        path = Schemafetcher.write_sample_json(field_tables(text))
    except Schemafetcher.SchemaError as e:
        print(f"WARNING: data DB schema unavailable, matching without it: {e}", file=sys.stderr)
        return "(not available)"
    lines = []
    for table, t in json.loads(path.read_text(encoding="utf-8"))["tables"].items():
        sample = t.get("sample") or {}
        lines.append(f"{table} (db table {t['db_table']}):")
        for fld, info in t["columns"].items():
            s = json.dumps(sample.get(fld), default=str, ensure_ascii=False)
            lines.append(f"  {fld}: {info['data_type']}" + (f"  sample={s[:80]}" if fld in sample else ""))
    return "\n".join(lines)


def main() -> None:
    field_desc = settings.field_desc_path.read_text(encoding="utf-8")
    queries = target_fields(field_desc)
    source = Path(settings.csv_path).name

    q_vecs = embedder.embed_texts(queries)
    with vector_store.connect() as conn:
        names = vector_store.column_names(conn, source)
        picked: dict[tuple[str, int], str] = {}
        for vec in q_vecs:
            for col, idx, content, _ in vector_store.search(conn, source, vec, settings.top_k_per_field):
                picked[(col, idx)] = content

    # One chunk per column is enough for the LLM; keep the earliest retrieved block.
    per_col: dict[str, str] = {}
    for (col, _), content in sorted(picked.items()):
        per_col.setdefault(col, content)
    context = "\n\n".join(per_col.values())

    user = prompts.SCHEMA_MATCH_USER.format(
        field_desc=field_desc, db_schema=db_schema_context(field_desc), format_tokens=prompts.FORMAT_TOKENS,
        column_context=context, column_names=", ".join(names))
    answer = llm.ask(prompts.SCHEMA_MATCH_SYSTEM, user)
    try:
        OUTPUT_PATH.write_text(json.dumps(json.loads(answer), indent=2), encoding="utf-8")
    except json.JSONDecodeError:
        # Keep the raw reply so nothing is lost, and leave the previous good file untouched.
        OUTPUT_PATH.with_suffix(".raw.txt").write_text(answer, encoding="utf-8")
        print(f"LLM reply was not valid JSON; raw text saved to {OUTPUT_PATH.with_suffix('.raw.txt')}")
        return
    print(f"saved -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
