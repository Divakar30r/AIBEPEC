import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql

from .config import settings


def chunks_table() -> sql.Identifier:
    return sql.Identifier(f"{settings.table_prefix}_chunks")


def connect() -> psycopg.Connection:
    """Open a connection to vector_db with the pgvector adapter registered."""
    conn = psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        dbname=settings.pg_db,
        user=settings.pg_user,
        password=settings.pg_password,
    )
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()
    register_vector(conn)
    return conn


def init_schema(conn: psycopg.Connection) -> None:
    table = chunks_table()
    index = sql.Identifier(f"{settings.table_prefix}_chunks_embedding_idx")
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {table} (
                    id BIGSERIAL PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    chunk_index INT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}',
                    embedding vector({dim}) NOT NULL,
                    UNIQUE (source_type, source, chunk_index)
                )
                """
            ).format(table=table, dim=sql.Literal(settings.embedding_dim))
        )
        # HNSW supports at most 2000 dims; above that fall back to exact scan.
        if settings.embedding_dim <= 2000:
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {index} ON {table} "
                    "USING hnsw (embedding vector_cosine_ops)"
                ).format(index=index, table=table)
            )
    conn.commit()
