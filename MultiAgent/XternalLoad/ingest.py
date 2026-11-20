"""Chunk the CSV column-wise, embed with OpenAI, store in Postgres/pgvector.

    python ingest.py             # chunk + embed + store
    python ingest.py --dry-run   # chunk only, no API / DB calls
"""
from __future__ import annotations

import argparse

import chunker
import embedder
import store
from config import settings


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
    with store.connect() as conn:
        store.init_schema(conn)
        store.upsert_chunks(conn, chunks, vectors)
    print(f"stored in {settings.pg_db}.{settings.pg_table}")


if __name__ == "__main__":
    main()
