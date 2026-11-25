"""Chunk the CSV column-wise, embed with OpenAI, store in the vector DB (via DBHandler).

    python ingest.py             # chunk + embed + store
    python ingest.py --dry-run   # chunk only, no API / DB calls
"""
from __future__ import annotations

import argparse
import sys

import chunker
import embedder
from config import HERE, settings

sys.path.insert(0, str(HERE.parent / "DBHandler"))
import vector_store  # noqa: E402  (DBHandler: the only DB client)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    chunks = chunker.chunk_csv()
    print(f"{len(chunks)} chunks ({len({c.column_name for c in chunks})} columns x "
          f"{len({c.chunk_idx for c in chunks})} row blocks of {settings.row_chunk_size} rows)")
    if args.dry_run:
        return
    vectors = embedder.embed_texts([c.content for c in chunks])
    with vector_store.connect() as conn:
        vector_store.init_schema(conn)
        vector_store.upsert_chunks(conn, chunks, vectors)
    print(f"stored in {vector_store.VECTOR_DB.name}.{vector_store.VECTOR_DB.table}")


if __name__ == "__main__":
    main()
