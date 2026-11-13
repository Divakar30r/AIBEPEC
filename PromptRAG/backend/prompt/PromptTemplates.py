"""All prompt templates live here (see .claude/RULES/PromptFileRule.MD).

A template is a complete chat message list (roles + text). Fetch one with
``get_prompt(name, **variables)``; never build prompt strings or messages in other modules.
Templates use named ``{placeholders}`` only.

Chat templates (rag-default, few-shot, chain-of-thought) share these variables:
  query (the search input), chosen_file, list_files, eval_scores, rag_outputs, question
(`question` is the user's chat message). `zero-shot-eval` takes: query, file_name, text.
"""

from string import Formatter

Message = dict[str, str]

# Shared RAG context block, placed in the system message of every chat template.
_CONTEXT = (
    "Search input: {query}\n"
    "Files: {list_files}\n"
    "Eval scores (0-1, per file): {eval_scores}\n"
    "RAG outputs:\n{rag_outputs}"
)

TEMPLATES: dict[str, list[Message]] = {
    # Zero-shot evaluation of one file's RAG output; run automatically after the semantic search.
    "zero-shot-eval": [
        {
            "role": "system",
            "content": "You evaluate retrieval results. Given a query and the text retrieved for "
            "it from one file, rate how well that text answers the query, from 0 (irrelevant) "
            "to 1 (fully relevant). Reply with only the number, with two decimal places, "
            "e.g. 0.73.",
        },
        {
            "role": "user",
            "content": "Query:\n{query}\n\nFile: {file_name}\nRetrieved text:\n{text}",
        },
    ],
    # Chat template used when no pattern name is given.
    "rag-default": [
        {
            "role": "system",
            "content": "Answer using only the RAG outputs below, focusing on the chosen file "
            "{chosen_file}. Cite files like [guide.pdf]. If they do not contain the answer, "
            "say so.\n\n" + _CONTEXT,
        },
        {"role": "user", "content": "{question}"},
    ],
    # Prompt patterns (selectable in the UI).
    "few-shot": [
        {
            "role": "system",
            "content": "Reason about the RAG output.\n\n" + _CONTEXT,
        },
        {
            "role": "user",
            "content": "Can you explain the score of RAG results against the {chosen_file} "
            "for the search input {query}?",
        },
        {
            "role": "assistant",
            "content": "The eval score of RAG results against {chosen_file} is 0.85, which "
            "indicates a high level of relevance and accuracy in the retrieved information.",
        },
        {"role": "user", "content": "is the search term present exactly in RAG output?"},
        {
            "role": "assistant",
            "content": "On searching the RAG output, the search term is present exactly in one "
            "of the retrieved chunks.",
        },
        {"role": "user", "content": "{question}"},
    ],
    "chain-of-thought": [
        {
            "role": "system",
            "content": "You are a helpful assistant and already evaluated RAG outputs against "
            "files for a given search input. Your task is to reason about the RAG output and "
            "provide insights based on the following questions:\n"
            "1. Does the RAG output contain the search input exactly in the {chosen_file}?\n"
            "2. Do the RAG eval scores align with the search input found in the RAG output?\n"
            "3. If the search input is not found in the RAG output, reason why.\n"
            "4. If the search input is found in the RAG output, compare the RAG eval score "
            "with the other files.\n\n"
            "Problem: RAG outputs against files {list_files} for the search input {query}, "
            "on your analysis evaluated scores are {eval_scores}\n\n"
            "RAG outputs:\n{rag_outputs}",
        },
        {"role": "user", "content": "{question}"},
    ],
}

# Templates the user can pick as a prompt pattern.
PATTERN_NAMES: tuple[str, ...] = ("few-shot", "chain-of-thought")


def get_prompt(name: str, **variables: str) -> list[Message]:
    """Return the message list for template ``name`` filled with ``variables``.

    Raises ValueError for an unknown name (listing valid ones) or for missing/unknown variables.
    """
    try:
        messages = TEMPLATES[name]
    except KeyError:
        raise ValueError(
            f"Unknown prompt template {name!r}. Valid names: {', '.join(sorted(TEMPLATES))}"
        ) from None

    needed = {f for m in messages for _, f, _, _ in Formatter().parse(m["content"]) if f}
    missing, unknown = needed - variables.keys(), variables.keys() - needed
    if missing:
        raise ValueError(f"Prompt {name!r} is missing variable(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"Prompt {name!r} got unknown variable(s): {', '.join(sorted(unknown))}")
    return [{"role": m["role"], "content": m["content"].format(**variables)} for m in messages]
