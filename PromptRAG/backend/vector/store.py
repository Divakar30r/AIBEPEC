import json
from collections.abc import Iterable

import psycopg
from psycopg import sql

from ..db import chunks_table, init_schema
from ..models import Document
from .chunking import chunk_document
from .embedder import embed_texts


def clear_source_type(conn: psycopg.Connection, source_type: str) -> int:
    """Delete every stored chunk of a source type ("git" or "pdf") ahead of a fresh load.

    Returns the number of chunks deleted.
    """
    init_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("DELETE FROM {t} WHERE source_type = %s").format(t=chunks_table()),
            (source_type,),
        )
        deleted = cur.rowcount
    conn.commit()
    return deleted


def ingest_documents(conn: psycopg.Connection, docs: Iterable[Document]) -> int:
    """Chunk, embed and store documents. Re-ingesting a source replaces its old chunks.

    Returns the number of chunks stored.
    """
    init_schema(conn)
    table = chunks_table()
    total = 0
    for doc in docs:
        chunks = chunk_document(doc)
        if not chunks:
            print(f"  skip (empty): {doc.source}")
            continue
        vectors = embed_texts(chunks)
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {t} WHERE source_type = %s AND source = %s").format(t=table),
                (doc.source_type, doc.source),
            )
            cur.executemany(
                sql.SQL(
                    "INSERT INTO {t} (source_type, source, chunk_index, content, metadata, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s)"
                ).format(t=table),
                [
                    (doc.source_type, doc.source, i, text, json.dumps(doc.metadata), vec)
                    for i, (text, vec) in enumerate(zip(chunks, vectors))
                ],
            )
        conn.commit()  # one document per transaction
        total += len(chunks)
        print(f"  {doc.source}: {len(chunks)} chunks")
    return total
