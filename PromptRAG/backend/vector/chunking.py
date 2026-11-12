"""Chunking with LangChain recursive splitters.

- Prose (PDFs, markdown, text): RecursiveCharacterTextSplitter, paragraph first
  ("\\n\\n" -> "\\n" -> " " -> characters).
- Python code (git): language-aware RecursiveCharacterTextSplitter that splits on
  class / def boundaries before falling back to lines and characters.

Size and overlap are configurable (TEXT_CHUNK_* and CODE_CHUNK_* in .env).
"""

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from ..config import settings
from ..models import Document


def _check(size: int, overlap: int) -> None:
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be >= 0 and < size")


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """Paragraph-based recursive split for prose."""
    size = settings.text_chunk_size if size is None else size
    overlap = settings.text_chunk_overlap if overlap is None else overlap
    _check(size, overlap)
    if not text.strip():
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    return splitter.split_text(text)


def chunk_python(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """Language-based recursive split for Python source."""
    size = settings.code_chunk_size if size is None else size
    overlap = settings.code_chunk_overlap if overlap is None else overlap
    _check(size, overlap)
    if not text.strip():
        return []
    splitter = RecursiveCharacterTextSplitter.from_language(
        Language.PYTHON, chunk_size=size, chunk_overlap=overlap
    )
    return splitter.split_text(text)


def chunk_document(doc: Document) -> list[str]:
    """Chunk a document, choosing the splitter per segment."""
    parts = doc.segments if doc.segments is not None else [("text", doc.text)]
    chunks: list[str] = []
    for kind, text in parts:
        chunks.extend(chunk_python(text) if kind == "python" else chunk_text(text))
    return chunks
