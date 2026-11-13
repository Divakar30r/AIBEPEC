from dataclasses import dataclass, field


@dataclass
class Document:
    """A whole source document (one notebook, one PDF) before chunking."""

    source_type: str  # "git" or "pdf"
    source: str  # repo-relative path or pdf-relative path
    text: str
    metadata: dict = field(default_factory=dict)
    # Optional (kind, text) parts, kind = "text" or "python". When set, each part is chunked
    # with the matching splitter; otherwise the whole `text` is split as prose.
    segments: list[tuple[str, str]] | None = None


@dataclass
class RAGResult:
    """Semantic-search output for one query plus the LLM's evaluation of it."""

    rag_output: dict[str, str]  # file name (git path or pdf name) -> its best matching chunks
    scores: dict[str, float]  # file name -> LLM eval score, 0.00 - 1.00
    query: str = ""  # the search input these results belong to
