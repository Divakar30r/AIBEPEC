"""Configuration loaded from environment variables (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the chatbot exercise."""

    hf_token: str
    model_id: str
    provider: str
    max_new_tokens: int
    temperature: float
    repetition_penalty: float

    @property
    def is_configured(self) -> bool:
        """True when a real Hugging Face token has been supplied."""
        return bool(self.hf_token) and not self.hf_token.startswith("hf_xxx")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read settings once and cache them."""
    return Settings(
        hf_token=os.getenv("HUGGINGFACEHUB_API_TOKEN", "").strip(),
        model_id=os.getenv("HF_MODEL_ID", "deepseek-ai/DeepSeek-V4.1-Flash").strip(),
        provider=os.getenv("HF_PROVIDER", "auto").strip(),
        max_new_tokens=int(os.getenv("HF_MAX_NEW_TOKENS", "512")),
        temperature=float(os.getenv("HF_TEMPERATURE", "0.7")),
        repetition_penalty=float(os.getenv("HF_REPETITION_PENALTY", "1.03")),
    )
