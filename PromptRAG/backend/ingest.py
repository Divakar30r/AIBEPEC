"""CLI: load sources into the vector DB.

    uv run python -m backend.ingest git     # public GitHub repo folder
    uv run python -m backend.ingest pdf     # PDFs in PDF_DIR
    uv run python -m backend.ingest all
"""

import argparse

from . import read_files, read_git
from .db import connect
from .vector import clear_source_type, ingest_documents


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("source", choices=["git", "pdf", "all"])
    args = ap.parse_args()

    with connect() as conn:
        if args.source in ("git", "all"):
            print(f"Cleared {clear_source_type(conn, 'git')} old git chunks")
            print("Ingesting GitHub repo...")
            n = ingest_documents(conn, read_git.iter_documents())
            print(f"Git: {n} chunks stored")
        if args.source in ("pdf", "all"):
            print(f"Cleared {clear_source_type(conn, 'pdf')} old pdf chunks")
            print("Ingesting PDFs...")
            n = ingest_documents(conn, read_files.iter_documents())
            print(f"PDF: {n} chunks stored")


if __name__ == "__main__":
    main()
