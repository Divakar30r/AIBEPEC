"""ReviewUI API (FastAPI) - a thin layer over DataGenerator / Supervisor / LLMEffects for the React UI.
No business logic here: every action calls the same functions the Streamlit app uses.

    uv run uvicorn ReviewUI.backend.main:app --reload --port 8000      (from MultiAgent/)

Env overrides (tests): REVIEWUI_RUNS_DIR (run files), LLMFEEDBACK_PATH (LLMEffects/feedback.py).
If ReviewUI/frontend/dist exists (npm run build), the built UI is served at / as well.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import Supervisor  # noqa: F401  (puts DataGenerator and the MultiAgent root on sys.path)
import Supervisor.graph as sv
import generator  # noqa: E402
import review_logic  # noqa: E402
import weights as fb_weights  # noqa: E402
from schema import build_plan  # noqa: E402
from settings import load_config  # noqa: E402
from source import load_db_formats  # noqa: E402

app = FastAPI(title="ReviewUI")
LOCK = threading.Lock()  # one writer at a time on run files and LLMfeedback.json
LLM: bool | None = None  # None = DataGenerator config llm_review; tests set False


def _runs_dir(cfg) -> Path:
    return Path(os.environ.get("REVIEWUI_RUNS_DIR") or cfg.output_dir)


def _path(cfg, run_id: str) -> Path:
    p = _runs_dir(cfg) / f"run_{run_id}.json"
    if not p.exists():
        raise HTTPException(404, f"run {run_id} not found")
    return p


def _read(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _unit(data: dict[str, Any], unit_id: int) -> dict[str, Any]:
    u = next((x for x in data["units"] if x["unit_id"] == unit_id), None)
    if u is None:
        raise HTTPException(404, f"unit {unit_id} not found")
    return u


# --------------------------------------------------------------------------- config + runs
@app.get("/api/config")
def config() -> dict[str, Any]:
    cfg = load_config()
    plan = build_plan(cfg)
    return {"parent": cfg.parent, "key_field": cfg.key_field, "db_name": cfg.db_name, "units": cfg.units,
            "llm_review": cfg.llm_review,
            "children": {c: {"key_field": v["key_field"], "fk": v["fk"], "min": v["min_per_key"],
                             "max": v["max_per_key"]} for c, v in cfg.children.items()},
            "levels": [[f"{t}.{f}" for t, f in lv] for lv in plan.levels],
            "options": {"only": fb_weights.ONLY, "max": fb_weights.MAX},
            "list_fields": sorted(fb_weights._feedback_module().list_fields())}  # the only ones LLM feedback takes


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    out = []
    for p in sorted(_runs_dir(load_config()).glob("run_*.json"), reverse=True):
        try:
            d = _read(p)
        except (OSError, json.JSONDecodeError):
            continue
        st = [u["status"] for u in d.get("units", [])]
        out.append({"run_id": d.get("run_id", p.stem[4:]), "units": len(st), "completed": st.count("completed"),
                    "needs_review": st.count("needs_review"), "error": st.count("error"),
                    "done": generator.run_done(d), "status": (d.get("supervisor") or {}).get("status")})
    return out


@app.get("/api/runs/{run_id}")
def run(run_id: str) -> dict[str, Any]:
    """The run file, plus per unit: its current LLM review and (halted units) the edit plan - editable cells
    with their in-cell editor (rule options for that row), prefills, and records proposed for deletion."""
    cfg = load_config()
    p = _path(cfg, run_id)
    d = _read(p)
    if generator.run_done(d) and not d.get("feedback_collected"):
        with LOCK:  # same as Streamlit: a finished run's outcome goes into LLMfeedback.json once
            generator.collect_if_done(p)
        d = _read(p)
    reviews = review_logic.load_llm_review(p, d["run_id"])
    rules, dbf = review_logic.rules_dump(cfg), load_db_formats(cfg)
    for u in d["units"]:
        rv = review_logic.llm_for(reviews, u)
        u["llm_review"] = rv
        u["edit"] = review_logic.edit_plan(cfg, rules, dbf, u, rv) if u["status"] == "needs_review" else None
    return d


class FieldOptions(BaseModel):
    table: str
    fields: list[str]
    values: dict[str, Any]  # {"Table.Field": value} - the record + its parent, unsaved edits included


@app.post("/api/field-options")
def field_options(body: FieldOptions) -> dict[str, Any]:
    """Editor per field of one record (Edit dialog): a dropdown for a list rule only once every field it
    depends on has a value - see review_logic.field_options."""
    cfg = load_config()
    return review_logic.field_options(cfg, review_logic.rules_dump(cfg), load_db_formats(cfg), body.table,
                                      body.fields, body.values)


class NewRun(BaseModel):
    units: int
    seed: int | None = None
    per_key: dict[str, tuple[int, int]]


@app.post("/api/runs")
def new_run(body: NewRun) -> dict[str, Any]:
    """Execute / Run again: one new supervised run (generate -> repair -> LLM -> wait | audit)."""
    with LOCK:
        st = sv.start(units=body.units, seed=body.seed or None, per_key=dict(body.per_key), llm=LLM)
    return {"run_id": Path(st["run_path"]).stem[4:]}


class Fix(BaseModel):
    table: str
    record: int | None = None
    field: str
    value: Any


class Rerun(BaseModel):
    fixes: list[Fix] = []
    deletions: dict[str, list[int]] = {}


@app.post("/api/runs/{run_id}/units/{unit_id}/rerun")
def rerun(run_id: str, unit_id: int, body: Rerun) -> dict[str, Any]:
    """Apply the reviewer's corrections / record deletions, re-run the unit from its halted level, then the
    supervisor's next pass (human feedback done)."""
    cfg = load_config()
    p = _path(cfg, run_id)
    u = _unit(_read(p), unit_id)
    rules, dbf = review_logic.rules_dump(cfg), load_db_formats(cfg)
    fixes = []
    for f in body.fixes:  # values from the UI (ISO dates, numbers as text) -> the stored form
        spec = review_logic.editor_spec(cfg, rules, dbf, u, f.table, f.record, f.field)
        fixes.append({"table": f.table, "record": f.record, "field": f.field,
                      "value": review_logic.to_stored(spec, f.value)})
    if not fixes and not body.deletions:
        raise HTTPException(400, "nothing to apply")
    with LOCK:
        generator.rerun_in_file(p, unit_id, fixes, cfg, deletions=body.deletions or None, llm=False)
        sv.resume(p, trigger="human", llm=LLM)
    return {"status": _unit(_read(p), unit_id)["status"]}


class UnitIds(BaseModel):
    unit_ids: list[int]


@app.post("/api/runs/{run_id}/llm-apply")
def llm_apply(run_id: str, body: UnitIds) -> dict[str, Any]:
    """Apply the LLM's A) conversions of these units and re-run them."""
    cfg = load_config()
    p = _path(cfg, run_id)
    with LOCK:
        res = generator.apply_llm_conversions(p, body.unit_ids, cfg)
    return {str(k): v for k, v in res.items()}


@app.delete("/api/runs/{run_id}/units/{unit_id}")
def delete_unit(run_id: str, unit_id: int) -> dict[str, Any]:
    p = _path(load_config(), run_id)
    _unit(_read(p), unit_id)
    with LOCK:
        generator.delete_unit_in_file(p, unit_id)
    return {"deleted": unit_id}


# --------------------------------------------------------------------------- LLM feedback
@app.get("/api/feedback")
def feedback() -> dict[str, Any]:
    return fb_weights.load_feedback()


def _clean(r: dict[str, Any]) -> dict[str, Any]:
    """Drop UI-only keys (leading '_'); typed Weightage / Count; empty Option removed."""
    r = {k: v for k, v in r.items() if not str(k).startswith("_")}
    r["Weightage"] = max(-1.0, min(1.0, float(r.get("Weightage") or 0)))
    if "Count" in r:
        r["Count"] = int(r.get("Count") or 0)
    if not r.get("Option"):
        r.pop("Option", None)
    return r


@app.put("/api/feedback")
def save_feedback(body: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """The full lists in priority order (rows marked Remove already left out by the UI)."""
    data = {s: [_clean(r) for r in body.get(s, [])] for s in ("Value-based", "Count-based")}
    with LOCK:
        fb_weights.save_feedback(data)
    return {s: len(v) for s, v in data.items()}


class Pair(BaseModel):
    section: str  # "Value-based" | "Count-based"
    row: dict[str, Any]
    run_id: str | None = None
    unit_id: int | None = None  # with run_id: a Never (-1) pair removes this unit from the run


@app.post("/api/feedback/pair")
def add_pair(body: Pair) -> dict[str, Any]:
    """'Add error to LLM feedback' - added at the bottom (lowest priority); -1 also removes the unit, its data
    kept with the pair (same as the Streamlit dialog)."""
    if body.section not in ("Value-based", "Count-based"):
        raise HTTPException(400, "section must be Value-based or Count-based")
    row = {**body.row, "Seen": 0, "Note": body.row.get("Note") or "added from UI"}
    never = float(row.get("Weightage") or 0) <= -1
    meta, p = None, None
    if never and body.run_id is not None and body.unit_id is not None:
        p = _path(load_config(), body.run_id)
        u = _unit(_read(p), body.unit_id)
        meta = {"run_id": body.run_id, "unit_id": u["unit_id"], "key": u["key"], "status": u["status"],
                "halted_before_level": u["halted_before_level"], "attempts": u.get("attempts", 0),
                "violations": u["violations"], "draft": u["draft"], "removed_at": datetime.now().isoformat()}
    if not fb_weights._feedback_module().is_list_pair(body.section, row):
        raise HTTPException(400, "Only fields with a list (ListStr) rule can be added to LLM feedback")
    with LOCK:
        fb_weights.add_pair(body.section, _clean(row), meta)
        if meta is not None:
            generator.delete_unit_in_file(p, body.unit_id)
    return {"added": body.section, "unit_removed": meta is not None}


DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():  # production: the built React app on the same port
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
