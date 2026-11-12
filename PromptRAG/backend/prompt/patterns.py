"""Prompt patterns the user can attach to a question. Their text is embedded with the question."""

PATTERNS: dict[str, str] = {
    "zero-shot": "Answering a task directly with no examples, relying only on the instruction.",
    "few-shot": "Teaching the task by giving a few worked input/output examples in the prompt.",
    "chain-of-thought": "Eliciting step-by-step reasoning before the final answer.",
    "self-consistency": "Sampling several reasoning paths and choosing the most consistent answer.",
    "role": "Assigning the model a persona or role to shape tone and expertise.",
    "task-decomposition": "Breaking a complex task into smaller sub-tasks.",
    "prompt-chaining": "Feeding the output of one prompt into the next in a sequence.",
    "negative-prompting": "Stating what the model should avoid or exclude.",
    "constrained-generation": "Constraining output format, length or structure.",
    "templates": "Reusable prompt templates with variables.",
    "instruction-engineering": "Writing clear, specific, well-structured instructions.",
    "ambiguity-clarity": "Reducing ambiguity and improving clarity of prompts.",
    "safety": "Prompt security, injection defence and ethical use.",
}


def list_patterns() -> list[str]:
    return list(PATTERNS)


def render_query(query: str, patterns: list[str] | None = None) -> str:
    """Combine the user question with the chosen patterns into the text to embed."""
    query = query.strip()
    chosen = [p for p in (patterns or []) if p in PATTERNS]
    if not chosen:
        return query
    lines = [f"Prompt pattern: {p} - {PATTERNS[p]}" for p in chosen]
    return "\n".join(lines) + f"\nQuestion: {query}"
