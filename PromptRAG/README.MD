# PromptRAG

Exploring RAG for prompt engineering: a Streamlit chatbot that answers from a vector database
built out of a public GitHub repo and local PDFs.

## Project structure

```
PromptRAG/
├── .claude/
│   └── settings.json        Claude Code permissions for this project
├── backend/
│   ├── config.py            Settings loaded from .env (secrets, DB, models, chunking)
│   ├── db.py                Postgres connection and PromptRAG_* table/index creation
│   ├── models.py            Shared dataclasses (Document, Hit, ChatResponse)
│   ├── ingest.py            CLI that loads sources into the vector DB
│   ├── prompt/              Prompt patterns and query rendering
│   ├── read_git/            Reads a public GitHub repo folder (notebooks, md, txt, py)
│   ├── read_files/          Reads .pdf files from the PDF folder
│   ├── vector/              Chunking, OpenAI embeddings, storing into pgvector
│   └── search/              Semantic search and chat() entry point used by the UI
├── frontend/
│   └── app.py               Streamlit chatbot UI
├── data/
│   └── pdfs/                Drop PDFs here to be ingested
├── tests/                   pytest tests for backend and frontend
├── .env.example             Template for the .env file (copy to .env, never commit .env)
├── pyproject.toml           Project metadata and dependencies (uv)
├── requirements.txt         Pinned dependencies exported from uv
├── uv.lock                  uv lockfile
├── CLAUDE.MD                Project instructions for Claude Code
└── README.MD                This file
```

`.venv/` (created by `uv sync`) is git-ignored and not shown.

## Data flow

1. **Ingest:** `read_git` and `read_files` produce documents, `vector` chunks and embeds them,
   and they are stored in the `PromptRAG_chunks` table of the `vector_db` Postgres database.
2. **Chat:** the UI passes the question and chosen prompt patterns to `backend.search.chat()`,
   which embeds them together, runs a semantic search and returns the answer and its sources.
