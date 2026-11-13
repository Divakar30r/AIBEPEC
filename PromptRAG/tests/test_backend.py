import json

import pytest

from backend.prompt import get_prompt
from backend.models import Document
from backend.read_git import notebook_to_segments, notebook_to_text, parse_github_url
from backend.vector import chunk_document, chunk_python, chunk_text


def test_chunk_text_overlap_and_progress():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_text(text, size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert chunks[0].split()[-1] in chunks[1]  # overlap carried over


def test_chunk_text_empty_and_invalid():
    assert chunk_text("   ") == []
    with pytest.raises(ValueError):
        chunk_text("x", size=10, overlap=10)


def test_parse_github_url():
    url = "https://github.com/NirDiamant/Prompt_Engineering/tree/main/all_prompt_engineering_techniques"
    assert parse_github_url(url) == (
        "NirDiamant", "Prompt_Engineering", "main", "all_prompt_engineering_techniques"
    )
    assert parse_github_url("https://github.com/o/r") == ("o", "r", None, "")


def test_notebook_to_text_drops_outputs():
    nb = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Title\n", "text"]},
            {"cell_type": "code", "source": ["print(1)"], "outputs": [{"text": "SECRET"}]},
        ]
    }
    out = notebook_to_text(json.dumps(nb))
    assert "# Title" in out and "```python\nprint(1)\n```" in out and "SECRET" not in out


def test_notebook_segments_merge_same_kind():
    nb = {
        "cells": [
            {"cell_type": "markdown", "source": ["a"]},
            {"cell_type": "markdown", "source": ["b"]},
            {"cell_type": "code", "source": ["x = 1"]},
        ]
    }
    assert notebook_to_segments(json.dumps(nb)) == [("text", "a\n\nb"), ("python", "x = 1")]


def test_chunk_python_splits_on_definitions():
    code = "\n\n".join(f"def f{i}():\n    return {i}\n" + "    # pad\n" * 8 for i in range(10))
    chunks = chunk_python(code, size=200, overlap=0)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert all(c.lstrip().startswith("def ") for c in chunks)  # cut at def boundaries


def test_chunk_document_routes_by_segment_kind():
    doc = Document("git", "n.ipynb", "", segments=[("text", "hello world"), ("python", "x = 1")])
    assert chunk_document(doc) == ["hello world", "x = 1"]
    assert chunk_document(Document("pdf", "a.pdf", "plain text")) == ["plain text"]


CHAT_VARS = {
    "query": "SEARCHTERM",
    "chosen_file": "a.pdf",
    "list_files": "a.pdf, b.md",
    "eval_scores": "a.pdf: 0.90, b.md: 0.12",
    "rag_outputs": "[a.pdf]\nAAA\n\n[b.md]\nBBB",
    "question": "Q",
}


@pytest.mark.parametrize("name", ["rag-default", "few-shot", "chain-of-thought"])
def test_chat_templates_render_with_query_scores_and_outputs(name):
    msgs = get_prompt(name, **CHAT_VARS)
    assert msgs[0]["role"] == "system" and msgs[-1] == {"role": "user", "content": "Q"}
    system = msgs[0]["content"]
    assert "SEARCHTERM" in system and "a.pdf: 0.90" in system and "AAA" in system


def test_few_shot_turns():
    few = get_prompt("few-shot", **CHAT_VARS)
    assert [m["role"] for m in few] == ["system", "user", "assistant", "user", "assistant", "user"]


def test_get_prompt_errors():
    with pytest.raises(ValueError, match="few-shot"):  # lists valid names
        get_prompt("nope")
    with pytest.raises(ValueError, match="missing"):
        get_prompt("rag-default", query="x")
    with pytest.raises(ValueError, match="unknown"):
        get_prompt("rag-default", **CHAT_VARS, extra="x")


def test_evaluate_scores_each_file_and_clamps(monkeypatch):
    from backend.search import search

    out = {"a.pdf": "text", "b.md": "more"}
    replies = iter(["0.734", "Score: 1.5"])
    monkeypatch.setattr(search, "complete", lambda messages: next(replies))
    assert search.evaluate("q", out) == {"a.pdf": 0.73, "b.md": 1.0}
    monkeypatch.setattr(search, "complete", lambda messages: "no idea")
    with pytest.raises(ValueError):
        search.evaluate("q", out)


def test_chat_sends_query_scores_and_all_files(monkeypatch):
    from backend.models import RAGResult
    from backend.search import search

    sent = []
    monkeypatch.setattr(search, "complete", lambda messages: sent.append(messages) or "ok")
    rag = RAGResult({"a.pdf": "AAA", "b.md": "BBB"}, {"a.pdf": 0.9, "b.md": 0.12}, "SEARCHTERM")
    assert search.chat("why?", rag, "b.md", "few-shot") == "ok"
    system = sent[0][0]["content"]
    assert "SEARCHTERM" in system and "a.pdf: 0.90, b.md: 0.12" in system
    assert "AAA" in system and "BBB" in system
    assert sent[0][-1]["content"] == "why?"
    assert "choose" in search.chat("why?", rag, "zzz")
