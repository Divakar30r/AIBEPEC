"""All database settings in one place, read from DBHandler/.env.

Two independent connections, named so they can't be confused:

  VECTORDB_*  - Postgres + pgvector store for embeddings (used by XternalLoad)
  DATADB_*    - the real data database whose schema drives data generation (used by DataGenerator)

No other folder reads DB settings or opens DB connections; they go through DBHandler.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")


def _env(prefix: str, name: str, default: str = "") -> str:
    return os.getenv(f"{prefix}_{name}", default)


@dataclass(frozen=True)
class PgConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    def connect_kwargs(self) -> dict:
        return dict(host=self.host, port=self.port, dbname=self.name, user=self.user,
                    password=self.password, connect_timeout=5)


@dataclass(frozen=True)
class VectorDBConfig(PgConfig):
    table: str = "csv_column_chunks"
    embed_dim: int = 1536


@dataclass(frozen=True)
class DataDBConfig(PgConfig):
    schema: str = "public"


def _pg(prefix: str) -> dict:
    return dict(host=_env(prefix, "HOST", "localhost"), port=int(_env(prefix, "PORT", "5432")),
                name=_env(prefix, "NAME"), user=_env(prefix, "USER", "postgres"),
                password=_env(prefix, "PASSWORD"))


# ---- Vector DB (embeddings) -------------------------------------------------
VECTOR_DB = VectorDBConfig(**_pg("VECTORDB"), table=_env("VECTORDB", "TABLE", "csv_column_chunks"),
                           embed_dim=int(_env("VECTORDB", "EMBED_DIM", "1536")))

# ---- Data DB (actual tables) ------------------------------------------------
DATA_DB = DataDBConfig(**_pg("DATADB"), schema=_env("DATADB", "SCHEMA", "public"))
