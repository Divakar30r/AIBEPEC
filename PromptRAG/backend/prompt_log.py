"""Per-UI-session log of every prompt sent to the LLM (responses are deliberately not logged).

The UI calls ``start_session`` once per Streamlit session and ``bind_session`` on every script
run; ``llm.complete`` calls ``log_prompt``. Outside a UI session (e.g. the ingest CLI) nothing
is logged.
"""

from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .config import settings

_log_file: ContextVar[Path | None] = ContextVar("prompt_log_file", default=None)


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def start_session() -> Path:
    """Create the log file for a new UI session and return its path."""
    settings.prompt_log_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = settings.prompt_log_path / f"session_{stamp}_{uuid4().hex[:6]}.log"
    path.write_text(f"[{_now()}] SESSION STARTED\n", encoding="utf-8")
    return path


def bind_session(path: Path) -> None:
    """Make ``path`` the active log for the current script run (Streamlit reruns each turn)."""
    _log_file.set(path)


def log_prompt(messages: list[dict[str, str]], label: str = "") -> None:
    """Append the exact messages sent to the model, with a timestamp. No-op without a session."""
    path = _log_file.get()
    if path is None:
        return
    lines = [f"\n[{_now()}] PROMPT{f' ({label})' if label else ''}"]
    for m in messages:
        lines.append(f"--- {m['role']} ---\n{m['content']}")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
