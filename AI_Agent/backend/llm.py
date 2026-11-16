"""Chat model client: a Hugging Face model reached through an OpenAI-compatible endpoint."""

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .config import settings
from .prompt import get_prompt

_llm: BaseChatModel | None = None


def get_llm() -> BaseChatModel:
    global _llm
    if _llm is None:
        if not settings.huggingfacehub_api_token:
            raise RuntimeError("HUGGINGFACEHUB_API_TOKEN is not set in .env")
        model = settings.hf_model_id
        if settings.hf_provider:
            model = f"{model}:{settings.hf_provider}"  # HF router syntax for picking a provider
        _llm = ChatOpenAI(
            model=model,
            base_url=settings.hf_base_url,
            api_key=settings.huggingfacehub_api_token,
            max_tokens=settings.hf_max_new_tokens,
            temperature=settings.hf_temperature,
        )
    return _llm


def set_llm(llm: BaseChatModel | None) -> None:
    """Swap the model (tests use a fake one); ``None`` resets to the configured model."""
    global _llm
    _llm = llm


def ask(prompt_name: str, **variables) -> str:
    """Fill the named template, send it to the model and return the reply text."""
    reply = get_llm().invoke(get_prompt(prompt_name, **variables))
    return reply.content if isinstance(reply.content, str) else str(reply.content)
