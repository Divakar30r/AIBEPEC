"""LangGraph supervisor: routes between the agents by plain rules (no LLM call in the supervisor).

    START -> route -> generate -> route -> repair -> route -> llm -> route -> await_human (END)
                                                                      \\-> audit -> END  (round over)
Routing (re-evaluated after every node, from the run file = persistent state):
  no run yet                                         -> generate   (Agent 1)
  halted units, repair not run in this pass          -> repair     (B, no LLM)
  halted units, LLM on, units not yet seen by the LLM -> llm        (Agent 2)
  units still halted / in error                      -> await_human (Agent 3, END - the UI resumes the graph)
  all units completed, round not yet audited         -> audit      (A, report only)
  otherwise                                          -> END
A round = everything until all units are completed; each human correction starts a new pass (round + 1).

    uv run python -m Supervisor.graph --units 10 --seed 7 [--no-llm]
    uv run python -m Supervisor.graph --resume DataGenerator/output/run_X.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import ROOT  # noqa: F401  (sets sys.path)
import generator  # noqa: E402
from settings import load_config  # noqa: E402

from . import audit as audit_agent  # noqa: E402
from . import repair as repair_agent  # noqa: E402


class SVState(TypedDict, total=False):
    run_path: str | None
    trigger: str           # start | human
    round: int
    done: list[str]        # nodes already run in this pass
    llm: bool              # whether the LLM agent may be called
    status: str
    overrides: dict[str, Any]
    per_key: dict[str, tuple[int, int]] | None


# --------------------------------------------------------------------------- run-file helpers
def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sv_update(path: str, **kv: Any) -> None:
    data = _load(path)
    sv = data.setdefault("supervisor", {"round": 1, "trace": [], "status": "", "llm_seen": {}, "audited_round": None})
    trace = kv.pop("trace", None)
    sv.update(kv)
    if trace:
        sv["trace"].append({**trace, "at": datetime.now().isoformat(timespec="seconds")})
    Path(path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _trace(state: SVState, node: str, summary: str) -> None:
    _sv_update(state["run_path"], round=state["round"], trace={"round": state["round"], "node": node,
                                                               "summary": summary})


def _halted(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [u for u in data["units"] if u["status"] == "needs_review"]


def _unseen_by_llm(data: dict[str, Any]) -> list[int]:
    seen = (data.get("supervisor") or {}).get("llm_seen", {})
    return [u["unit_id"] for u in _halted(data) if seen.get(str(u["unit_id"])) != u.get("attempts", 0)]


# --------------------------------------------------------------------------- router
def route(state: SVState) -> str:
    if not state.get("run_path"):
        return "generate"
    data = _load(state["run_path"])
    done = state.get("done", [])
    halted = _halted(data)
    if halted and "repair" not in done:
        return "repair"
    if halted and state.get("llm") and "llm" not in done and _unseen_by_llm(data):
        return "llm"
    if halted or any(u["status"] != "completed" for u in data["units"]):
        return "await_human"
    if generator.run_done(data) and (data.get("supervisor") or {}).get("audited_round") != state["round"]:
        return "audit"
    return END


# --------------------------------------------------------------------------- nodes (agents)
def generate(state: SVState) -> SVState:
    cfg = load_config(per_key=state.get("per_key"), **{**state.get("overrides", {}), "llm_review": False})
    out = str(generator.run(cfg))  # Agent 1: no LLM inside; the supervisor decides when the LLM runs
    data = _load(out)
    state = {**state, "run_path": out}
    _sv_update(out, round=state["round"], status="running", llm_seen={}, audited_round=None)
    _trace(state, "generate", f"{len(data['units'])} units: {len(_halted(data))} halted, "
                              f"{sum(u['status'] == 'completed' for u in data['units'])} completed")
    return {"run_path": out, "done": state.get("done", []) + ["generate"]}


def repair(state: SVState) -> SVState:
    res = repair_agent.run_repair(state["run_path"], load_config())
    swaps = ", ".join(f"u{u}<-u{d}" for u, d in sorted(res["assignment"].items()))
    if res["applied"]:
        fixed = [u for u, s in res["applied"].items() if s == "completed"]
        rest = len(res["applied"]) - len(fixed)
        msg = (f"swapped related sets ({swaps}); {len(fixed)} unit(s) completed without an LLM call"
               + (f", {rest} still halted (took a leftover set)" if rest else ""))
    else:
        msg = f"no swap fixes a halted unit (groups by level {res['groups']}, {res['checked']} combinations checked)"
    _trace(state, "repair", msg)
    return {"done": state.get("done", []) + ["repair"]}


def llm(state: SVState) -> SVState:
    path = state["run_path"]
    ids = _unseen_by_llm(_load(path))
    cfg = load_config()
    err = generator.llm_review(Path(path), ids, trigger=state.get("trigger", "run"))
    res = {} if err else generator.apply_llm_conversions(path, ids, cfg)
    data = _load(path)
    seen = dict((data.get("supervisor") or {}).get("llm_seen", {}))
    for u in data["units"]:  # remember which attempt the LLM has seen, so a new pass doesn't re-ask it
        if u["unit_id"] in ids:
            seen[str(u["unit_id"])] = u.get("attempts", 0)
    _sv_update(path, llm_seen=seen)
    done_n = sum(1 for s in res.values() if s == "completed")
    _trace(state, "llm", err or f"{len(ids)} unit(s) reviewed; A) conversions completed {done_n}, "
                                f"{len(ids) - done_n} still halted")
    return {"done": state.get("done", []) + ["llm"]}


def await_human(state: SVState) -> SVState:
    data = _load(state["run_path"])
    n = sum(1 for u in data["units"] if u["status"] != "completed")
    _sv_update(state["run_path"], status="awaiting_human")
    _trace(state, "await_human", f"{n} unit(s) need corrections in the UI")
    return {"status": "awaiting_human", "done": state.get("done", []) + ["await_human"]}


def audit(state: SVState) -> SVState:
    rep = audit_agent.audit_run(state["run_path"], load_config(), state["round"])
    _sv_update(state["run_path"], audited_round=state["round"], status="done")
    s = rep["summary"]
    _trace(state, "audit", "round complete - " + ", ".join(
        f"{a}: {v['violations']} violation(s) / {v['checks']} check(s)" for a, v in s.items()))
    return {"status": "done", "done": state.get("done", []) + ["audit"]}


# --------------------------------------------------------------------------- graph
def build():
    g = StateGraph(SVState)
    targets = {"generate": "generate", "repair": "repair", "llm": "llm", "await_human": "await_human",
               "audit": "audit", END: END}
    for name, fn in (("generate", generate), ("repair", repair), ("llm", llm), ("await_human", await_human),
                     ("audit", audit)):
        g.add_node(name, fn)
    g.add_conditional_edges(START, route, targets)
    for name in ("generate", "repair", "llm", "audit"):
        g.add_conditional_edges(name, route, targets)
    g.add_edge("await_human", END)
    return g.compile()


GRAPH = build()


def start(units: int | None = None, seed: int | None = None, per_key: dict | None = None,
          llm: bool | None = None) -> SVState:
    """New run, supervised from generation to the first human wait (or to the audit if nothing halts)."""
    llm = load_config().llm_review if llm is None else llm
    return GRAPH.invoke({"run_path": None, "trigger": "start", "round": 1, "done": [], "llm": llm,
                         "overrides": {k: v for k, v in (("units", units), ("seed", seed)) if v is not None},
                         "per_key": per_key})


def resume(run_path: str | Path, trigger: str = "human", llm: bool | None = None) -> SVState:
    """After human corrections: a new pass (round + 1) - repair, LLM for units it hasn't seen, then wait/audit."""
    data = _load(str(run_path))
    rnd = int((data.get("supervisor") or {}).get("round", 1)) + 1
    llm = load_config().llm_review if llm is None else llm
    return GRAPH.invoke({"run_path": str(run_path), "trigger": trigger, "round": rnd, "done": [], "llm": llm})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--resume")
    a = ap.parse_args()
    st = resume(a.resume, llm=not a.no_llm) if a.resume else start(a.units, a.seed, llm=not a.no_llm)
    data = _load(st["run_path"])
    for t in data["supervisor"]["trace"]:
        print(f"[round {t['round']}] {t['node']:<11} {t['summary']}")
    print(f"status: {data['supervisor']['status']} -> {st['run_path']}")


if __name__ == "__main__":
    main()
