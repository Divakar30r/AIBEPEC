"""Postgres + pgvector storage for column chunks."""
from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector

from chunker import ColumnChunk
from config import Settings, settings


def connect(cfg: Settings = settings) -> psycopg.Connection:
    # The extension must exist before the vector type can be registered.
    with psycopg.connect(cfg.pg_dsn, autocommit=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn = psycopg.connect(cfg.pg_dsn)
    register_vector(conn)
    return conn


def init_schema(conn: psycopg.Connection, cfg: Settings = settings) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {cfg.pg_table} (
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


def upsert_chunks(conn: psycopg.Connection, chunks: list[ColumnChunk],
                  embeddings: list[list[float]], cfg: Settings = settings) -> None:
    sql = f"""
        INSERT INTO {cfg.pg_table}
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
           cfg: Settings = settings) -> list[tuple[str, int, str, float]]:
    """Nearest chunks by cosine distance -> (column_name, chunk_idx, content, distance)."""
    return conn.execute(
        f"""SELECT column_name, chunk_idx, content, embedding <=> %s::vector AS dist
            FROM {cfg.pg_table} WHERE source = %s ORDER BY dist LIMIT %s""",
        (query_embedding, source, k)).fetchall()


def column_names(conn: psycopg.Connection, source: str, cfg: Settings = settings) -> list[str]:
    rows = conn.execute(f"SELECT DISTINCT column_name FROM {cfg.pg_table} WHERE source = %s", (source,)).fetchall()
    return sorted(r[0] for r in rows)
