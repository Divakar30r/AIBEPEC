"""Vector DB (VECTORDB_* in DBHandler/.env): Postgres + pgvector storage for column-profile chunks.

Chunks are any objects with: source, column_name, chunk_idx, row_start, row_end, content.
"""
from __future__ import annotations

from typing import Any, Sequence

import psycopg
from pgvector.psycopg import register_vector

from db_config import VECTOR_DB, VectorDBConfig


def connect(cfg: VectorDBConfig = VECTOR_DB) -> psycopg.Connection:
    if not cfg.name:
        raise RuntimeError("VECTORDB_NAME is not set (see DBHandler/.env.example)")
    # The extension must exist before the vector type can be registered.
    with psycopg.connect(**cfg.connect_kwargs(), autocommit=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn = psycopg.connect(**cfg.connect_kwargs())
    register_vector(conn)
    return conn


def init_schema(conn: psycopg.Connection, cfg: VectorDBConfig = VECTOR_DB) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {cfg.table} (
            id          BIGSERIAL PRIMARY KEY,
            source      TEXT NOT NULL,
            column_name TEXT NOT NULL,
            chunk_idx   INT  NOT NULL,
            row_start   INT  NOT NULL,
            row_end     INT  NOT NULL,
            content     TEXT NOT NULL,
            embedding   vector({cfg.embed_dim}) NOT NULL,
            UNIQUE (source, column_name, chunk_idx)
        )""")
    conn.commit()


def upsert_chunks(conn: psycopg.Connection, chunks: Sequence[Any],
                  embeddings: list[list[float]], cfg: VectorDBConfig = VECTOR_DB) -> None:
    sql = f"""
        INSERT INTO {cfg.table}
            (source, column_name, chunk_idx, row_start, row_end, content, embedding)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source, column_name, chunk_idx) DO UPDATE SET
            row_start = EXCLUDED.row_start, row_end = EXCLUDED.row_end,
            content = EXCLUDED.content, embedding = EXCLUDED.embedding"""
    with conn.cursor() as cur:
        cur.executemany(sql, [(c.source, c.column_name, c.chunk_idx, c.row_start, c.row_end, c.content, e)
                              for c, e in zip(chunks, embeddings)])
    conn.commit()


def search(conn: psycopg.Connection, source: str, query_embedding: list[float], k: int,
           cfg: VectorDBConfig = VECTOR_DB) -> list[tuple[str, int, str, float]]:
    """Nearest chunks by cosine distance -> (column_name, chunk_idx, content, distance)."""
    return conn.execute(
        f"""SELECT column_name, chunk_idx, content, embedding <=> %s::vector AS dist
            FROM {cfg.table} WHERE source = %s ORDER BY dist LIMIT %s""",
        (query_embedding, source, k)).fetchall()


def column_names(conn: psycopg.Connection, source: str, cfg: VectorDBConfig = VECTOR_DB) -> list[str]:
    rows = conn.execute(f"SELECT DISTINCT column_name FROM {cfg.table} WHERE source = %s", (source,)).fetchall()
    return sorted(r[0] for r in rows)
