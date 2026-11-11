# CLAUDE.MD — Project Constraints & Standard Procedures

## Project
Learning sandbox comparing LangChain prompt-template strategies against a
Hugging Face Inference Providers model. Not production software.

- Package root: `src/chatbot/`
- Entry point: `python -m chatbot` (launches Streamlit)
- Python: 3.13, managed with `uv` in `.venv`

## Hard Constraints
1. **Secrets never enter source.** All credentials live in `.env`, loaded via
   `python-dotenv` in `config.py`. `.env` is git-ignored; `.env.example` is the
   only committed template. Never print or log a token.
2. **Single source of configuration.** Read settings only through
   `chatbot.config.get_settings()`. Do not call `os.getenv` elsewhere.
3. **No RAG, no tools, no agents.** This exercise is strictly about prompt
   templates and chat history. Do not introduce retrievers, vector stores,
   `@tool`, `AgentExecutor`, or `create_agent`.
4. **No deprecated LangChain APIs.** `LLMChain`, `ConversationChain`, and
   `ConversationBufferMemory` are banned. Compose with LCEL
   (`prompt | model | parser`).
5. **Two strategies stay symmetric.** `from_messages` and `from_template` must
   receive the identical question, `max_sentences`, and generation settings so
   differences are attributable to the template alone.
6. **Type hints on every function.** `from __future__ import annotations` at the
   top of each module; `dataclass` for structured state.

## Standard Procedures
- **Dependencies:** edit `pyproject.toml` *and* `requirements.txt` together, then
  run `uv pip install -r requirements.txt`. Never hand-install into `.venv`
  without recording it in both files.
- **Run the app:** `uv run streamlit run src/chatbot/frontend.py`
  (or `uv run python -m chatbot`).
- **Verify before claiming done:** `uv run python -c "import chatbot.frontend"`
  must succeed, and the Streamlit app must start without traceback.
- **Do not run test scripts.** The author troubleshoots and learns from errors
  hands-on. Do not write or execute verification/test scripts, `AppTest` harnesses,
  or throwaway `_verify_*.py` files unless explicitly asked. Static checks
  (imports, reading code) are fine; runtime assertions are the author's job.
- **Errors in the UI:** provider/auth failures are caught and rendered inline in
  the affected column; never swallow an exception silently.
- **Prompt inspection:** every strategy must expose the exact rendered prompt
  (`Session.render_prompt`) so the comparison is evidence-based, not assumed.
- **Style:** line length 100, double quotes, module docstrings explaining *why*
  the module exists.
- **Git:** conventional-commit style messages; never commit `.env`, `.venv`, or
  `__pycache__`.

## Out of Scope (for now)
Streaming responses, persistence beyond in-memory history, auth, deployment,
evaluation harnesses, and any non-Hugging-Face model provider.

## Tool Permissions

### Allowed without confirmation
| Operation | Scope |
|-----------|-------|
| **Edit/create files** | Any path under the project root (`CHatbot/**`) — accept all edits without confirmation |
| **Read file contents** | `Get-Content`, `cat`, `type`, or any other read command on any path under `CHatbot/**` |
| **Read terminal output** | Capture and return stdout/stderr from any command executed in the project environment |
| **Web fetch** | `Invoke-WebRequest`, `curl`, `web_fetch` — any HTTP GET to any external URL |
| **Web search** | Any web-search tool or API (e.g. Bing, Google, DuckDuckGo) |
| **PyPI installs** | `pip install`, `uv pip install`, `uv add` — any package from `pypi.org` |

### Requires explicit permission
| Operation | Scope |
|-----------|-------|
| **Delete files/directories** | `Remove-Item`, `del`, `rm`, `os.remove` — any destructive removal under `CHatbot/**` |
| **Rename/move files** | `Rename-Item`, `Move-Item`, `mv`, `os.rename` — any path under `CHatbot/**` |

### Always prohibited
- Writing secrets, credentials, or tokens into tracked source files
- Executing code that modifies system-level configuration outside the project
