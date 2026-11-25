"""Stateless LLM call (HF router, OpenAI-compatible): one system + one user message, no history."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from settings import Settings


RETRIES = int(os.getenv("LLMEFFECTS_RETRIES", "4"))  # extra attempts after a rate limit / temporary error
BACKOFF = (10, 30, 60, 120)  # seconds between attempts, unless the provider says how long (Retry-After)
# "Thinking" models (e.g. DeepSeek-V4.1-Flash) otherwise spend the whole max_tokens on hidden reasoning and
# return no text. "none" switches it off; set LLMEFFECTS_REASONING_EFFORT= (empty) to leave the model default.
REASONING_EFFORT = os.getenv("LLMEFFECTS_REASONING_EFFORT", "none")


def _wait_for(err: Exception, attempt: int) -> float:
    headers = getattr(getattr(err, "response", None), "headers", None) or {}
    try:
        return min(300.0, float(headers.get("retry-after")))
    except (TypeError, ValueError):
        return float(BACKOFF[min(attempt, len(BACKOFF) - 1)])


def ask(system: str, user: str, cfg: Settings) -> str:
    if not cfg.hf_token:
        raise RuntimeError("HUGGINGFACEHUB_API_TOKEN is not set in LLMEffects/.env (see LLMEffects/.env.example)")
    client = OpenAI(base_url=cfg.hf_base_url, api_key=cfg.hf_token)
    for attempt in range(RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=cfg.hf_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=cfg.hf_temperature, max_tokens=cfg.hf_max_new_tokens,
                **({"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}),
            )
            choice = resp.choices[0]
            text = choice.message.content or ""
            if not text.strip() and choice.finish_reason == "length":
                raise RuntimeError(f"LLM reply cut off at max_tokens={cfg.hf_max_new_tokens} before any text "
                                   "(hidden reasoning used the budget) - raise LLMEFFECTS_MAX_TOKENS or keep "
                                   "LLMEFFECTS_REASONING_EFFORT=none")
            return text
        except (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError) as e:
            if attempt == RETRIES:
                raise
            wait = _wait_for(e, attempt)
            print(f"LLM {type(e).__name__}; retry {attempt + 1}/{RETRIES} in {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def parse_json(text: str) -> Any:
    """Tolerant: strips ``` fences / leading prose, parses the outermost JSON object."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text
    body = body.strip()
    if body.startswith('"'):  # some models drop the outer brace: '"units": {...}}'
        body = "{" + body
    start = body.find("{")
    if start < 0:
        raise ValueError("no JSON object in LLM reply")
    try:  # parse the first complete object, ignore anything after it
        return json.JSONDecoder().raw_decode(body[start:])[0]
    except json.JSONDecodeError:
        return json.loads(body[start:body.rfind("}") + 1])
