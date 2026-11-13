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
│   ├── models.py            Shared dataclasses (Document, RAGResult)
│   ├── ingest.py            CLI that loads sources into the vector DB
│   ├── llm.py               Hugging Face LLM client (OpenAI-compatible provider endpoint)
│   ├── prompt/              PromptTemplates.py (all prompts) and pattern names
│   ├── read_git/            Reads a public GitHub repo folder (notebooks, md, txt, py)
│   ├── read_files/          Reads .pdf files from the PDF folder
│   ├── vector/              Chunking, OpenAI embeddings, storing into pgvector
│   └── search/              Per-file semantic search, LLM eval score and chat()
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
2. **Query (once):** the UI sends the query to `backend.search.run_rag()`, which compares it against
   every file and stores the best chunks per file in a `RAGOutput` dict (file name -> text). The
   HF LLM then scores each file's text 0.00-1.00 with the zero-shot `zero-shot-eval` template.
3. **Chat:** the user picks a `chosen_file` and optionally a pattern (few-shot, chain-of-thought)
   and converses with the LLM via `backend.search.chat()` over the RAG output of all files, focused on the chosen file.
