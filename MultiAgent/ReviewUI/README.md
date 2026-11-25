# ReviewUI - React review UI

A React review UI for DataGenerator runs. It replaces the Streamlit tables, and Streamlit (`DataGenerator/app.py`) still works alongside it.

- `backend/` is a thin FastAPI layer over DataGenerator, Supervisor and LLMEffects. It has no business logic of its own, and the shared review logic lives in `DataGenerator/review_logic.py`.
- `frontend/` is Vite + React + TypeScript. Every table is one component, `src/EditableGrid.tsx`, built on Material React Table. It provides:
  - editors inside the cells (rule dropdowns for that row, ranges, dates, text)
  - an Options column that locks that row's cells at once
  - row dragging for priority (turned off while grouped)
  - group by any columns (drag a header to the drop zone)
  - per-column value filters

## Run (from `MultiAgent/`)
```
uv pip install -r ReviewUI/backend/requirements.txt          # once
cd ReviewUI/frontend && npm install && npm run build && cd ../..   # once / after UI changes
uv run uvicorn ReviewUI.backend.main:app --port 8000         # API + built UI -> http://localhost:8000
```
To develop with hot reload, run the API as above, then `npm run dev` in `ReviewUI/frontend`. Open http://localhost:5173; `/api` is forwarded to port 8000.

## Screens
- **Review:**
  - All units (group or filter by status or halted level).
  - Per halted unit, its tables: red cells are flagged, and editable cells hold the rule's options for that row, prefilled with the LLM's proposal. Typing a value overrides the options.
  - A related record's Options can be set to Delete.
  - Actions: Apply & re-run, Apply LLM conversions, Add error to LLM feedback, Remove unit.
- **LLM feedback:**
  - Value-based and Count-based pairs. Drag rows for priority, and filter with the weightage chips and column filters.
  - Options locking: Remove locks every cell except Options; Only Possibility locks every cell; Max Possibility leaves only Weightage editable.
  - Save writes `LLMEffects/LLMfeedback.json`.
- **Supervisor:** the agent trace and the end-of-round audit (grouped by author, with a "violations only" switch).

## Tests
`uv run python -m pytest ReviewUI/backend/test_api.py -q` runs on a temporary runs folder and a temporary feedback file, with no LLM calls. It needs the data DB, like the generator.
