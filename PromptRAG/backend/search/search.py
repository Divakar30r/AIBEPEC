from psycopg import sql

from ..config import settings
from ..db import chunks_table, connect
from ..models import ChatResponse, Hit
from ..prompt import render_query
from ..vector.embedder import embed_texts, get_client


def semantic_search(
    query: str, patterns: list[str] | None = None, top_k: int | None = None
) -> list[Hit]:
    """Embed the question together with the chosen prompt patterns and return nearest chunks."""
    top_k = top_k or settings.top_k
    vec = embed_texts([render_query(query, patterns)])[0]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT content, source_type, source, chunk_index, 1 - (embedding <=> %s::vector) "
                "FROM {t} ORDER BY embedding <=> %s::vector LIMIT %s"
            ).format(t=chunks_table()),
            (vec, vec, top_k),
        )
        return [Hit(*row) for row in cur.fetchall()]


def _passages(hits: list[Hit]) -> str:
    out = []
    for i, h in enumerate(hits, 1):
        out.append(f"**{i}. {h.source}** ({h.source_type}, match {h.score:.2f})\n{h.content}")
    return "\n\n---\n\n".join(out)


def chat(query: str, patterns: list[str] | None = None) -> ChatResponse:
    """Entry point for the UI: question (+ patterns) in, chat answer + sources out."""
    if not query.strip():
        return ChatResponse("Please enter a question.", [])

    hits = semantic_search(query, patterns)
    if not hits:
        return ChatResponse("Nothing is indexed yet. Run the ingest step first.", [])

    if not settings.chat_model:
        return ChatResponse("Top matches from the knowledge base:\n\n" + _passages(hits), hits)

    context = "\n\n".join(f"[{i}] ({h.source})\n{h.content}" for i, h in enumerate(hits, 1))
    resp = get_client().chat.completions.create(
        model=settings.chat_model,
        messages=[
            {
                "role": "system",
                "content": "Answer using only the numbered context. Cite sources like [1]. "
                "If the context does not contain the answer, say so.",
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {render_query(query, patterns)}"},
        ],
    )
    return ChatResponse(resp.choices[0].message.content or "", hits)
