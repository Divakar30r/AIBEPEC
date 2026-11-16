"""Postgres access: the target DB (DDL) and the vector_db log tables (prefix from settings)."""

import psycopg
from psycopg import sql

from .config import settings


def connect(dbname: str) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        dbname=dbname,
        user=settings.pg_user,
        password=settings.pg_password,
    )


def connect_target() -> psycopg.Connection:
    """Connection to the DB the scripts are generated for and executed against."""
    return connect(settings.pg_target_db)


def script_log_table() -> sql.Identifier:
    return sql.Identifier(f"{settings.table_prefix}_script_log")


def log_script(script: str, status: str, detail: str = "") -> None:
    """Record an executed script (and its outcome) in vector_db."""
    table = script_log_table()
    with connect(settings.pg_log_db) as conn:
        conn.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {table} (
                    id BIGSERIAL PRIMARY KEY,
                    executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    target_db TEXT NOT NULL,
                    target_schema TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    script TEXT NOT NULL
                )
                """
            ).format(table=table)
        )
        conn.execute(
            sql.SQL(
                "INSERT INTO {table} (target_db, target_schema, status, detail, script) "
                "VALUES (%s, %s, %s, %s, %s)"
            ).format(table=table),
            (settings.pg_target_db, settings.target_schema, status, detail, script),
        )
