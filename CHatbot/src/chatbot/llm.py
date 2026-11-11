"""Model factory for Hugging Face Inference Providers via LangChain."""

from __future__ import annotations

import os
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

from chatbot.config import get_settings


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    """Build (once) a chat model routed to the configured HF provider."""
    settings = get_settings()

    if not settings.is_configured:
        raise RuntimeError(
            "HUGGINGFACEHUB_API_TOKEN is missing. Copy `.env.example` to `.env` "
            "and paste a real token from https://huggingface.co/settings/tokens"
        )

    # langchain-huggingface reads the token from this variable.
    os.environ["HUGGINGFACEHUB_API_TOKEN"] = settings.hf_token

    endpoint = HuggingFaceEndpoint(
        repo_id=settings.model_id,
        task="conversational",
        provider=settings.provider,
        max_new_tokens=settings.max_new_tokens,
        temperature=settings.temperature,
        repetition_penalty=settings.repetition_penalty,
    )
    return ChatHuggingFace(llm=endpoint)
