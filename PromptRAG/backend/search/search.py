import re

from psycopg import sql

from ..config import settings
from ..db import chunks_table, connect
from ..llm import complete
from ..models import RAGResult
from ..prompt import get_prompt
from ..vector.embedder import embed_texts

RAGOutput = dict[str, str]  # file name -> best matching chunks of that file


def list_files() -> list[str]:
    """Names of every indexed file (git paths and PDFs)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT DISTINCT source FROM {t} ORDER BY source").format(t=chunks_table())
        )
        return [row[0] for row in cur.fetchall()]


def semantic_search(query: str, per_file: int | None = None) -> RAGOutput:
    """Compare the query against every file and keep each file's best chunks."""
    per_file = per_file or settings.chunks_per_file
    vec = embed_texts([query])[0]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT source, content FROM ("
                "  SELECT source, content, "
                "         ROW_NUMBER() OVER (PARTITION BY source ORDER BY embedding <=> %s::vector) rn "
                "  FROM {t}"
                ") ranked WHERE rn <= %s ORDER BY source, rn"
            ).format(t=chunks_table()),
            (vec, per_file),
        )
        out: RAGOutput = {}
        for source, content in cur.fetchall():
            out[source] = f"{out[source]}\n\n{content}" if source in out else content
        return out


def _as_text(rag_output: RAGOutput) -> str:
    return "\n\n".join(f"[{name}]\n{text}" for name, text in rag_output.items())


def _scores_text(scores: dict[str, float]) -> str:
    return ", ".join(f"{name}: {score:.2f}" for name, score in scores.items())


def evaluate(query: str, rag_output: RAGOutput) -> dict[str, float]:
    """Ask the LLM (zero-shot) to score each file's retrieved text for the query, 0.00 - 1.00."""
    scores: dict[str, float] = {}
    for file_name, text in rag_output.items():
        reply = complete(get_prompt("zero-shot-eval", query=query, file_name=file_name, text=text))
        match = re.search(r"\d*\.?\d+", reply)
        if not match:
            raise ValueError(f"Evaluator did not return a score for {file_name}: {reply!r}")
        scores[file_name] = round(min(max(float(match.group()), 0.0), 1.0), 2)
    return scores


def run_rag(query: str) -> RAGResult:
    """Semantic search over all files, then automatically evaluate each file's result."""
    query = query.strip()
    rag_output = semantic_search(query)
    return RAGResult(rag_output, evaluate(query, rag_output) if rag_output else {}, query)


def chat(
    question: str, rag: RAGResult, chosen_file: str, template: str | None = None
) -> str:
    """Converse with the LLM over the RAG output and eval scores of ALL files, for one chosen file.

    `question` is the chat message; `rag.query` is the original search input.
    `template` is a prompt template name (e.g. few-shot, chain-of-thought); default when None.
    """
    if not question.strip():
        return "Please enter a question."
    if chosen_file not in rag.rag_output:
        return "Please choose one of the retrieved files."
    return complete(
        get_prompt(
            template or "rag-default",
            query=rag.query,
            chosen_file=chosen_file,
            list_files=", ".join(rag.rag_output),
            eval_scores=_scores_text(rag.scores),
            rag_outputs=_as_text(rag.rag_output),
            question=question,
        )
    )
