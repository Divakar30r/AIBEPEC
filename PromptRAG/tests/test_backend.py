import json

import pytest

from backend.prompt import render_query
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


def test_render_query():
    assert render_query("hi") == "hi"
    out = render_query("hi", ["few-shot", "bogus"])
    assert "few-shot" in out and "bogus" not in out and out.endswith("Question: hi")
