"""Stateless LLM call: Hugging Face router -> Featherless AI, via the OpenAI client."""
from __future__ import annotations

from openai import OpenAI

from config import Settings, settings


def ask(system: str, user: str, cfg: Settings = settings) -> str:
    if not cfg.hf_token:
        raise RuntimeError("HUGGINGFACEHUB_API_TOKEN is not set (see .env.example)")
    client = OpenAI(base_url=cfg.hf_base_url, api_key=cfg.hf_token)
    # No history: every call is exactly one system + one user message.
    resp = client.chat.completions.create(
        model=cfg.hf_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=cfg.hf_temperature,
        max_tokens=cfg.hf_max_new_tokens,
    )
    return resp.choices[0].message.content or ""
