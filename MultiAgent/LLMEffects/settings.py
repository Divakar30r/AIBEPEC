"""LLMEffects settings: config.json + HF router secrets (.env here, else ../XternalLoad/.env)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env", override=True)  # ours wins over values inherited from DataGenerator's environment
load_dotenv(HERE.parent / "XternalLoad" / ".env")  # fallback; does not override values already set


@dataclass(frozen=True)
class Settings:
    mask_fields: tuple[str, ...]
    max_rounds: int
    registry_dump: Path
    count_dump: Path
    field_desc: Path
    runs_dir: Path
    hf_token: str = os.getenv("HUGGINGFACEHUB_API_TOKEN", "")
    hf_model_id: str = os.getenv("HF_MODEL_ID", "deepseek-ai/DeepSeek-V4.1-Flash")
    hf_provider: str = os.getenv("HF_PROVIDER", "")
    hf_base_url: str = os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1")
    hf_max_new_tokens: int = int(os.getenv("LLMEFFECTS_MAX_TOKENS", "6000"))
    hf_temperature: float = float(os.getenv("HF_TEMPERATURE", "0.5"))

    @property
    def hf_model(self) -> str:
        return f"{self.hf_model_id}:{self.hf_provider}" if self.hf_provider else self.hf_model_id


def load_settings(path: Path = HERE / "config.json") -> Settings:
    c = json.loads(path.read_text(encoding="utf-8"))
    p = {k: (HERE / v).resolve() for k, v in c["paths"].items()}
    return Settings(mask_fields=tuple(c.get("mask_fields", [])), max_rounds=int(c.get("max_rounds", 2)), **p)
