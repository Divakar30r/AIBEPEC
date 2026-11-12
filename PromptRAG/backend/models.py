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
class Hit:
    content: str
    source_type: str
    source: str
    chunk_index: int
    score: float  # cosine similarity, higher is better


@dataclass
class ChatResponse:
    answer: str
    hits: list[Hit]
