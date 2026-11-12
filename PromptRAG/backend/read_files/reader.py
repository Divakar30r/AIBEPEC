"""Read .pdf files from the configured folder (default: data/pdfs)."""

from collections.abc import Iterator
from pathlib import Path

from pypdf import PdfReader

from ..config import settings
from ..models import Document


def iter_documents(folder: Path | None = None) -> Iterator[Document]:
    folder = folder or settings.pdf_path
    if not folder.is_dir():
        raise FileNotFoundError(f"PDF folder not found: {folder}")

    for pdf in sorted(folder.rglob("*.pdf")):
        try:
            reader = PdfReader(pdf)
            pages = [(p.extract_text() or "").strip() for p in reader.pages]
        except Exception as exc:  # corrupt / encrypted PDF: report and continue
            print(f"  skip (unreadable): {pdf.name}: {exc}")
            continue
        yield Document(
            source_type="pdf",
            source=pdf.relative_to(folder).as_posix(),
            text="\n\n".join(p for p in pages if p),
            metadata={"pages": len(pages)},
        )
