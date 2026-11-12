from openai import OpenAI

from ..config import settings

_BATCH = 64
_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in .env")
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts with the configured OpenAI model, in batches."""
    kwargs: dict = {"model": settings.embedding_model}
    # Only the text-embedding-3 family accepts a `dimensions` override.
    if settings.embedding_model.startswith("text-embedding-3"):
        kwargs["dimensions"] = settings.embedding_dim

    out: list[list[float]] = []
    client = get_client()
    for i in range(0, len(texts), _BATCH):
        batch = texts[i : i + _BATCH]
        resp = client.embeddings.create(input=batch, **kwargs)
        out.extend(d.embedding for d in resp.data)
    return out
