"""OpenAI embeddings."""
from __future__ import annotations

from openai import OpenAI

from config import Settings, settings


def _client(cfg: Settings) -> OpenAI:
    if not cfg.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set (see .env.example)")
    return OpenAI(api_key=cfg.openai_api_key)


def embed_texts(texts: list[str], cfg: Settings = settings) -> list[list[float]]:
    client = _client(cfg)
    out: list[list[float]] = []
    for i in range(0, len(texts), cfg.embed_batch):
        resp = client.embeddings.create(model=cfg.embed_model, input=texts[i:i + cfg.embed_batch])
        out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return out
