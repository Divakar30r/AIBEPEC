import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "frontend" / "app.py")


@pytest.fixture
def fake_backend(monkeypatch):
    """Stub backend.prompt / backend.search so the UI runs without OpenAI or Postgres."""
    calls = []

    class Hit:
        source, source_type, score = "few-shot-learning.ipynb", "git", 0.87

    class Resp:
        answer, hits = "Use examples.", [Hit()]

    def chat(query, patterns=None):
        calls.append((query, patterns))
        if query == "boom":
            raise RuntimeError("no api key")
        return Resp()

    pkg = types.ModuleType("backend")
    pkg.__path__ = []
    prompt = types.ModuleType("backend.prompt")
    prompt.list_patterns = lambda: ["few-shot", "role"]
    search = types.ModuleType("backend.search")
    search.chat = chat
    monkeypatch.setitem(sys.modules, "backend", pkg)
    monkeypatch.setitem(sys.modules, "backend.prompt", prompt)
    monkeypatch.setitem(sys.modules, "backend.search", search)
    return calls


def test_question_goes_to_chat_with_patterns(fake_backend):
    at = AppTest.from_file(APP).run()
    at.sidebar.multiselect[0].set_value(["few-shot"]).run()
    at.chat_input[0].set_value("How do I teach a task?").run()
    assert fake_backend == [("How do I teach a task?", ["few-shot"])]
    assert [m.markdown[0].value for m in at.chat_message][-1] == "Use examples."
    assert not at.exception


def test_backend_error_is_shown_not_raised(fake_backend):
    at = AppTest.from_file(APP).run()
    at.chat_input[0].set_value("boom").run()
    assert not at.exception
    assert "no api key" in at.chat_message[-1].markdown[0].value
