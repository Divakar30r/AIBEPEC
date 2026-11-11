"""Two prompt-template strategies used to answer the same question.

The point of this exercise is to see how the *shape* of a prompt template
changes the resulting `ChatPromptValue` that is sent to the model:

* `build_from_messages()`  -> ChatPromptTemplate.from_messages()
  A list of explicit role-tagged messages. Roles are structural, so the
  system instruction can never be swallowed by user input.

* `build_from_template()`  -> ChatPromptTemplate.from_template()
  A single f-string/Jinja string. Everything is one message, so the role
  boundary has to be faked with text and is therefore weaker.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# Roles are structural here: the system prompt is a real SystemMessage.
FROM_MESSAGES_TEMPLATE = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a concise, factual assistant. "
            "Answer in at most {max_sentences} sentences. "
            "If you are unsure, say so explicitly.",
        ),
        MessagesPlaceholder(variable_name="history", optional=True),
        ("human", "{question}"),
    ]
)

# Everything is a single string: the "role" is only text inside one message.
FROM_TEMPLATE_TEMPLATE = ChatPromptTemplate.from_template(
    "System: You are a concise, factual assistant. "
    "Answer in at most {max_sentences} sentences. "
    "If you are unsure, say so explicitly.\n\n"
    "User: {question}\n\n"
    "Assistant:"
)


def build_from_messages() -> ChatPromptTemplate:
    """Return the role-structured template built with `from_messages()`."""
    return FROM_MESSAGES_TEMPLATE


def build_from_template() -> ChatPromptTemplate:
    """Return the single-string template built with `from_template()`."""
    return FROM_TEMPLATE_TEMPLATE


def describe_templates() -> dict[str, dict[str, object]]:
    """Introspection data used by the UI to show what each template produces."""
    result: dict[str, dict[str, object]] = {}
    for key, template in (
        ("from_messages", FROM_MESSAGES_TEMPLATE),
        ("from_template", FROM_TEMPLATE_TEMPLATE),
    ):
        result[key] = {
            "input_variables": sorted(template.input_variables),
            "input_types": {k: [t.__name__ for t in v] for k, v in template.input_types.items()},
            "message_count": len(template.messages),
            "message_types": [type(m).__name__ for m in template.messages],
        }
    return result
