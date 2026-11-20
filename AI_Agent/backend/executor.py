"""Execute a generated DDL script against the target DB, all or nothing."""

import logging
from dataclasses import dataclass

from sqlparse import format as SQ_P_format, split as SQ_P_split
from psycopg import sql

from .BackendConstants import (
    ALLOWED_SCRIPT_KEYWORDS,
    FORBIDDEN_SCRIPT_PREFIXES,
    IGNORED_SCRIPT_KEYWORDS,
)
from .config import settings
from .db import connect_target, log_script

log = logging.getLogger(__name__)


@dataclass
class ExecResult:
    ok: bool
    message: str


def prepare_statements(script: str) -> list[str]:
    """Split ``script`` into statements and check each one is allowed.

    Transaction control (BEGIN/COMMIT) is dropped, since the whole script runs in one transaction.
    Raises ValueError for an empty script or a statement that is not permitted.
    """
    statements: list[str] = []
    for raw in SQ_P_split(script):
        text = SQ_P_format(raw, strip_comments=True).strip().rstrip(";").strip()
        if not text:
            continue
        upper = " ".join(text.upper().split())
        keyword = upper.split(" ", 1)[0]
        if keyword in IGNORED_SCRIPT_KEYWORDS:
            continue
        if keyword not in ALLOWED_SCRIPT_KEYWORDS:
            raise ValueError(
                f"Statement not allowed ({keyword}). Allowed: {', '.join(ALLOWED_SCRIPT_KEYWORDS)}"
            )
        if any(upper.startswith(prefix) for prefix in FORBIDDEN_SCRIPT_PREFIXES):
            raise ValueError(f"Statement not allowed: {upper[:40]}")
        statements.append(text)
    if not statements:
        raise ValueError("The script has no statements to run.")
    return statements


def summarize_script(script: str, max_len: int = 60) -> str:
    """One-line description of a script, e.g. ``CREATE TABLE orders (+2 more)``."""
    try:
        statements = prepare_statements(script)
    except ValueError:  # rejected script: still describe what was attempted
        statements = [s.strip() for s in SQ_P_split(script) if s.strip()]
    if not statements:
        return "(empty script)"
    head = " ".join(statements[0].split("(")[0].split())[:max_len]
    return head + (f" (+{len(statements) - 1} more)" if len(statements) > 1 else "")


def execute_script(script: str) -> ExecResult:
    """Run the script in a single transaction on the target DB; roll back on any error."""
    try:
        statements = prepare_statements(script)
        with connect_target() as conn, conn.transaction():
            conn.execute(
                sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(settings.target_schema))
            )
            for statement in statements:
                conn.execute(statement)
        result = ExecResult(True, f"Executed {len(statements)} statement(s) on {settings.pg_target_db}.")
    except Exception as exc:
        result = ExecResult(False, str(exc))

    try:
        log_script(script, "success" if result.ok else "failed", "" if result.ok else result.message)
    except Exception:  # logging must never hide the execution outcome
        log.exception("Could not write to the %s script log", settings.table_prefix)
    return result
