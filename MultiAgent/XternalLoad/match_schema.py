"""Match CSV columns (from pgvector) to FieldDesc.MD using an LLM.

For each target field line in FieldDesc.MD, retrieve the nearest column chunks, merge them
into one context, and make a single stateless LLM call.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import embedder
import llm
import prompts
import store
from config import HERE, settings

OUTPUT_PATH = Path(HERE / "last_mapping.json")


def target_fields(text: str) -> list[str]:
    """Lines like `"FieldName": description` -> one retrieval query each."""
    return [m.group(0).strip().rstrip(",") for m in re.finditer(r'^\s*"[A-Za-z]+"\s*:.*$', text, re.M)]


def main() -> None:
    field_desc = settings.field_desc_path.read_text(encoding="utf-8")
    queries = target_fields(field_desc)
    source = Path(settings.csv_path).name

    q_vecs = embedder.embed_texts(queries)
    with store.connect() as conn:
        names = store.column_names(conn, source)
        picked: dict[tuple[str, int], str] = {}
        for vec in q_vecs:
            for col, idx, content, _ in store.search(conn, source, vec, settings.top_k_per_field):
                picked[(col, idx)] = content

    # One chunk per column is enough for the LLM; keep the earliest retrieved block.
    per_col: dict[str, str] = {}
    for (col, _), content in sorted(picked.items()):
        per_col.setdefault(col, content)
    context = "\n\n".join(per_col.values())

    user = prompts.SCHEMA_MATCH_USER.format(
        field_desc=field_desc, column_context=context, column_names=", ".join(names))
    answer = llm.ask(prompts.SCHEMA_MATCH_SYSTEM, user)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
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
