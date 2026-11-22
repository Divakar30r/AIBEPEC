"""Stateless LLM call (HF router, OpenAI-compatible): one system + one user message, no history."""
from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from settings import Settings


def ask(system: str, user: str, cfg: Settings) -> str:
    if not cfg.hf_token:
        raise RuntimeError("HUGGINGFACEHUB_API_TOKEN is not set")
    client = OpenAI(base_url=cfg.hf_base_url, api_key=cfg.hf_token)
    resp = client.chat.completions.create(
        model=cfg.hf_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=cfg.hf_temperature, max_tokens=cfg.hf_max_new_tokens,
    )
    return resp.choices[0].message.content or ""


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
