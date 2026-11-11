"""Backend: run the same question through both prompt-template strategies."""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from chatbot.llm import get_chat_model
from chatbot.prompts import build_from_messages, build_from_template

STRATEGIES = ("from_messages", "from_template")


@dataclass
class Session:
    """One chat session: its own history plus the template it uses."""

    strategy: str
    history: list[BaseMessage] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {STRATEGIES}, got {self.strategy!r}")
        self._chain: Runnable | None = None

    @property
    def chain(self) -> Runnable:
        """Build the LCEL chain lazily so a missing token doesn't break startup."""
        if self._chain is None:
            self._chain = self._build_chain()
        return self._chain

    def _build_chain(self) -> Runnable:
        template = (
            build_from_messages()
            if self.strategy == "from_messages"
            else build_from_template()
        )
        return template | get_chat_model() | StrOutputParser()

    def render_prompt(self, question: str, max_sentences: int) -> str:
        """Return the exact text the model will receive (for side-by-side diffing)."""
        payload: dict[str, object] = {"question": question, "max_sentences": max_sentences}
        if self.strategy == "from_messages":
            payload["history"] = list(self.history)
        template = (
            build_from_messages()
            if self.strategy == "from_messages"
            else build_from_template()
        )
        return template.invoke(payload).to_string()

    def ask(self, question: str, max_sentences: int = 3) -> str:
        """Send a question, store the turn in history, and return the answer."""
        payload: dict[str, object] = {"question": question, "max_sentences": max_sentences}
        if self.strategy == "from_messages":
            payload["history"] = list(self.history)

        answer = self.chain.invoke(payload)

        self.history.append(HumanMessage(content=question))
        self.history.append(AIMessage(content=answer))
        return answer

    def reset(self) -> None:
        """Drop the conversation history."""
        self.history.clear()


def make_sessions() -> dict[str, Session]:
    """Create one session per strategy so the UI can run them in parallel."""
    return {strategy: Session(strategy=strategy) for strategy in STRATEGIES}
