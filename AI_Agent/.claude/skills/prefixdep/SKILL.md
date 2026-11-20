---
name: prefixdep
description: Prefix every name that backend/ imports from one dependency (e.g. langgraph -> LG_interrupt), so the origin of each call is visible in the code.
argument-hint: "<dependency in requirements.txt> <PREFIX>   e.g. langgraph LG"
disable-model-invocation: true
---

# PrefixDep

Arguments received: `$ARGUMENTS` = `<dependency> <PREFIX>`

Example: `/PrefixDep langgraph LG` turns `from langgraph.types import interrupt` into
`from langgraph.types import interrupt as LG_interrupt` and every use of `interrupt` into `LG_interrupt`.

## Steps

1. **Validate.** Both arguments are required. The dependency must be listed in `requirements.txt` (compare
   case-insensitively; treat `-` and `_` as the same, ignore version pins and extras). If it is missing, or the
   prefix is empty or not a valid Python identifier, stop and say so.
   **Wildcard:** a dependency ending in `*` (e.g. `langgraph*`) matches every package in `requirements.txt` whose
   name starts with the text before the `*` (`langgraph`, `langgraph-checkpoint`, `langgraph-prebuilt`,
   `langgraph-sdk`, ...); only top-level requirement lines count, not `# via` comments. Without `*` the
   dependency means exactly that one package (`langgraph` does not include `langgraph-checkpoint`). A wildcard
   that matches nothing is the same as a missing dependency. List the matched packages in the report. All
   matched packages get the same prefix.
2. **Find the import roots.** The import name can differ from the package name (e.g. `langchain-core` is
   imported as `langchain_core`). Take the package name with `-` replaced by `_`; if nothing in `backend/` imports
   it, check the installed package's top-level names (`uv run python -c "import importlib.metadata as m; print(m.packages_distributions())"`)
   and report what you used. Include sub-modules (`langgraph.graph`, `langgraph.types`, ...).
   Several packages can share one import root (`langgraph` is shipped by `langgraph`, `langgraph-checkpoint`,
   ...): decide which package a name belongs to by the file that defines it (`importlib.metadata.files`), and
   without `*` rename only the names that come from the named package.
3. **Scan** every `*.py` under `backend/` (include `prompt/`; skip `__pycache__`). List each
   `from <root>... import ...` and `import <root>...` with the names it brings in.
4. **Rename with an alias**, one name at a time, using `import ... as`:
   - `from langgraph.types import Command, interrupt` -> `from langgraph.types import Command as LG_Command, interrupt as LG_interrupt`
   - Rename every use of that name in the same file (calls, annotations, `Literal`/`Command[...]` subscripts,
     `isinstance`, etc.). Use word-boundary matching so `interrupts` or `my_interrupt` are not touched.

5. **Skip, and report as skipped:**
   - Names that already start with `<PREFIX>_` (the skill is safe to run twice).However if the prefixes differ then replace the old prefix with new.
   - Dotted attribute access on a module object, string literals, comments and docstrings (mention a name there
     only when it is the code's own identifier being described; otherwise leave it).
   - Anything inside `tests/` and `frontend/` (the scope is `backend/`), but list the places there that import
     the renamed names from `backend`, because they would break.
   - Re-exports: if a renamed name is imported by another module from `backend` (not from the dependency),
     update that importer too, or report it.
6. **Check:** run `uv run python -c "import backend.graph, backend.agent"` from the project root and fix any
   `NameError` or `ImportError` caused by the rename. Do not run the test suite; the user runs `/runtests`.
7. **Report** a short table: file, names renamed (old -> new), and the skipped items with the reason.

## Rules

- Change only `backend/`. Never edit `requirements.txt`, `.env` or `.venv`.
- Rename only; do not change behaviour, reformat or reorder imports beyond the alias.
- Do not commit or push (project rule: GH read only).
- Constants and prompts stay where the project rules put them (`BackendConstants.py`, `PromptTemplates.py`);
  this skill renames imported names only.
