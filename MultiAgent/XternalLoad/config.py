"""Central settings. Secrets come from .env / environment; tunables live here with env overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _csv_list(name: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in _env(name, default).split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    # ---- input files ------------------------------------------------------
    # required: the external file to profile. A relative path is taken relative to this folder
    # (XternalLoad/), not the shell's current directory.
    csv_path: str = str((HERE / _env("CSV_PATH", "")).resolve()) if _env("CSV_PATH", "") else ""
    field_desc_path: Path = Path(_env("FIELD_DESC_PATH", str(HERE.parent / "FieldDesc.MD")))

    # ---- chunking ---------------------------------------------------------
    row_chunk_size: int = int(_env("ROW_CHUNK_SIZE", "100"))  # rows per chunk (min rows per chunk)
    max_rows: int = int(_env("MAX_ROWS", "1000"))  # rows read from the CSV; 0 = all
    sample_values: int = int(_env("SAMPLE_VALUES", "8"))  # example values / top values per column chunk
    # Mixed-type handling: a column is mixed when its dominant kind is below 1 - MIX_THRESHOLD;
    # mixed columns are re-chunked into smaller row blocks for up to MIX_MAX_ROUNDS rounds.
    mix_threshold: float = float(_env("MIX_THRESHOLD", "0.10"))
    mix_max_rounds: int = int(_env("MIX_MAX_ROUNDS", "3"))
    profiler: str = _env("PROFILER", "frictionless").lower()  # frictionless | builtin
    # Extra columns whose raw values must never leave the machine (emails/phones/masked ids are
    # detected automatically); only value *shapes* are described.
    redact_columns: tuple[str, ...] = field(
        default_factory=lambda: _csv_list("REDACT_COLUMNS", "")
    )
    # Cell values treated as null (case-insensitive), besides empty cells.
    null_tokens: tuple[str, ...] = field(
        default_factory=lambda: _csv_list("NULL_TOKENS", "na,n/a,null,nan,nil,#n/a")
    )

    # ---- embeddings (OpenAI) ---------------------------------------------
    openai_api_key: str = _env("OPENAI_API_KEY", "")
    embed_model: str = _env("EMBED_MODEL", "text-embedding-3-small")
    embed_dim: int = int(_env("EMBED_DIM", "1536"))
    embed_batch: int = int(_env("EMBED_BATCH", "64"))

    # Database settings (vector DB) live in ../DBHandler/.env - DBHandler is the only DB client.

    # ---- LLM: Hugging Face router, Featherless AI provider (OpenAI-compatible)
    hf_token: str = _env("HUGGINGFACEHUB_API_TOKEN", "")
    hf_model_id: str = _env("HF_MODEL_ID", "Qwen/Qwen2.5-Coder-32B-Instruct")
    hf_provider: str = _env("HF_PROVIDER", "featherless-ai")  # appended to the model id as ':<provider>'
    hf_base_url: str = _env("HF_BASE_URL", "https://router.huggingface.co/v1")
    hf_max_new_tokens: int = int(_env("HF_MAX_NEW_TOKENS", "2000"))
    hf_temperature: float = float(_env("HF_TEMPERATURE", "0.1"))

    @property
    def hf_model(self) -> str:
        """Router model string, e.g. 'Qwen/Qwen2.5-Coder-32B-Instruct:featherless-ai'."""
        return f"{self.hf_model_id}:{self.hf_provider}" if self.hf_provider else self.hf_model_id

    # ---- retrieval for schema matching -----------------------------------
    top_k_per_field: int = int(_env("TOP_K_PER_FIELD", "6"))


settings = Settings()
