import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "frontend" / "app.py")


@pytest.fixture
def fake_backend(monkeypatch):
    """Stub backend.prompt / backend.search so the UI runs without LLM, OpenAI or Postgres."""
    calls = {"rag": [], "chat": []}

    class Result:
        rag_output = {"few-shot-learning.ipynb": "Use examples.", "guide.pdf": "RAG basics."}
        scores = {"few-shot-learning.ipynb": 0.85, "guide.pdf": 0.4}

    def run_rag(query):
        calls["rag"].append(query)
        if query == "boom":
            raise RuntimeError("no api key")
        return Result()

    def chat(question, rag, chosen_file=None, template=None):
        calls["chat"].append((question, chosen_file, template))
        return "Use examples."

    pkg = types.ModuleType("backend")
    pkg.__path__ = []
    prompt = types.ModuleType("backend.prompt")
    prompt.list_patterns = lambda: ["few-shot", "chain-of-thought"]
    search = types.ModuleType("backend.search")
    search.run_rag, search.chat = run_rag, chat
    search.list_files = lambda: ["few-shot-learning.ipynb", "guide.pdf"]
    monkeypatch.setitem(sys.modules, "backend", pkg)
    monkeypatch.setitem(sys.modules, "backend.prompt", prompt)
    monkeypatch.setitem(sys.modules, "backend.search", search)
    return calls


def _search(at, query):
    at.text_input[0].set_value(query)
    at.button(key="search_btn").click()
    return at.run()


def test_query_runs_rag_once_and_shows_score(fake_backend):
    at = AppTest.from_file(APP).run()
    assert at.chat_input[0].disabled  # chat locked until a query has run
    at = _search(at, "How do I teach a task?")
    assert fake_backend["rag"] == ["How do I teach a task?"]
    assert list(at.dataframe[0].value["score"]) == [0.85, 0.4]  # one score per file
    assert at.text_input[0].disabled  # query can be entered only once
    assert not at.exception


def test_chat_uses_chosen_file_and_pattern(fake_backend):
    at = _search(AppTest.from_file(APP).run(), "q")
    at.sidebar.selectbox[0].set_value("guide.pdf")
    at.sidebar.selectbox[1].set_value("few-shot")
    at.run()
    at.chat_input[0].set_value("Explain").run()
    assert fake_backend["chat"] == [("Explain", "guide.pdf", "few-shot")]
    assert at.chat_message[-1].markdown[0].value == "Use examples."
    assert not at.exception


def test_backend_error_is_shown_not_raised(fake_backend):
    at = _search(AppTest.from_file(APP).run(), "boom")
    assert not at.exception
    assert "no api key" in at.error[0].value


def test_controls_locked_until_query_is_processed(fake_backend):
    at = AppTest.from_file(APP).run()
    assert all(sb.disabled for sb in at.sidebar.selectbox)  # file + pattern
    assert at.chat_input[0].disabled
    assert "None (default)" not in at.sidebar.selectbox[1].options
    at = _search(at, "q")
    assert not any(sb.disabled for sb in at.sidebar.selectbox)
    assert not at.chat_input[0].disabled


def test_reset_clears_query_and_chat(fake_backend):
    at = _search(AppTest.from_file(APP).run(), "q")
    at.chat_input[0].set_value("Explain").run()
    assert len(at.chat_message) == 2
    at.button(key="reset_btn").click().run()
    assert len(at.chat_message) == 0
    assert at.text_input[0].value == "" and not at.text_input[0].disabled
    assert at.chat_input[0].disabled
