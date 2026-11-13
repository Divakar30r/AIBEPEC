"""Client for the Hugging Face hosted LLM used for evaluation and chat."""

from openai import OpenAI

from .config import settings

_client: OpenAI | None = None


def get_llm_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.huggingfacehub_api_token:
            raise RuntimeError("HUGGINGFACEHUB_API_TOKEN is not set in .env")
        _client = OpenAI(base_url=settings.hf_base_url, api_key=settings.huggingfacehub_api_token)
    return _client


def complete(messages: list[dict[str, str]]) -> str:
    """Run one chat completion with the configured HF model on the configured provider."""
    model = settings.hf_model_id
    if settings.hf_provider:
        model = f"{model}:{settings.hf_provider}"  # HF router syntax for picking the provider
    resp = get_llm_client().chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=settings.hf_max_new_tokens,
        temperature=settings.hf_temperature,
    )
    return resp.choices[0].message.content or ""
