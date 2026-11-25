"""Batched LLM review of a DataGenerator run's needs_review units -> llm_review_<run_id>.json (suggestions only).

    python review.py [run_file] [--units=1,4] [--trigger=rerun] [--print-prompt]   # default: newest run_*.json

Every LLM call is logged to logs/session_<run_id>_<ts>_r<round>.json (units sent, raw + parsed reply),
unless "session_log": false in config.json.

Round 1: one call for ALL halted units (A conversions, B count decisions, C suggestions).
A+B are applied to a copy and re-validated locally (no DB). Units still failing get ONE more batched call;
anything still failing/conflicting after max_rounds is marked skipped_conflict. The run file is not modified.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE.parent / "DAGRegistry", HERE.parent / "DataGenerator"):
    if str(p) not in sys.path:
        sys.path.append(str(p))
if sys.path[0] != str(HERE):
    sys.path.insert(0, str(HERE))  # our settings/llm win over DataGenerator's modules of the same name

import feedback  # noqa: E402
import prompts  # noqa: E402
from context import compact_counts, compact_rules, dumps, unit_payload  # noqa: E402
from llm import ask, parse_json  # noqa: E402
from settings import Settings, load_settings  # noqa: E402


# --------------------------------------------------------------------------- local validation (read-only reuse)
def _validate(draft: dict[str, Any], registry, count_dump) -> list[dict[str, Any]]:
    from count_rules import check_counts  # DataGenerator/count_rules.py
    parent = next(t for t, d in draft.items() if isinstance(d, dict))

    def rows(table: str, record, ctx):
        return [{"kind": "field", "table": v.table, "field": v.field, "record": record, "value": v.value,
                 "reason": v.reason} for v in registry.validate_row(ctx) if v.table == table]

    out = rows(parent, None, {parent: draft[parent]})
    for child, recs in draft.items():
        if child != parent:
            for i, rec in enumerate(recs):
                out += rows(child, i, {parent: draft[parent], child: rec})
    attempted = {f"{t}.{f}" for t, d in draft.items() for rec in ([d] if isinstance(d, dict) else d) for f in rec}
    return out + check_counts(count_dump, draft, attempted)


def _screen(draft: dict[str, Any], conv: list[dict[str, Any]], registry,
            blocked: set[tuple] = frozenset()) -> tuple[list, list]:
    """Keep only A) conversions whose target is a real value that passes its field rule.
    Rejected ones (e.g. "__delete__", a value not allowed under the current guards, or a pair the user set
    to -1 in LLMfeedback.json) are never applied."""
    keep, rejected = [], []
    for c in conv:
        to = c.get("to")
        if to in (None, "") or str(to).startswith("__") or c.get("field") == "__delete__":
            rejected.append({**c, "rejected": "not a value (deletions belong in count_decisions)"})
            continue
        if (c.get("table"), c.get("field"), feedback.norm(c.get("from")), str(to)) in blocked:
            rejected.append({**c, "rejected": "forbidden by the user (weight -1)"})
            continue
        fixed, bad = _apply(draft, keep + [c])
        cell = (c.get("table"), c.get("record"), c.get("field"))
        if bad or any((v["table"], v["record"], v["field"]) == cell
                      for v in _validate(fixed, registry, None) if v["kind"] == "field"):
            rejected.append({**c, "rejected": "target value violates its rule"})
            continue
        keep.append(c)
    return keep, rejected


def _apply(draft: dict[str, Any], changes: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Apply A+B to a copy. Conflict = same cell given two different values, or an invalid target cell."""
    d, seen, conflicts, deletes = copy.deepcopy(draft), {}, [], {}
    for c in changes:
        t, r, f, to = c.get("table"), c.get("record"), c.get("field"), c.get("to")
        if t not in d:
            conflicts.append(f"unknown table {t}")
            continue
        if f == "__delete__":
            deletes.setdefault(t, set()).add(r)
            continue
        cell = (t, r, f)
        if cell in seen and seen[cell] != to:
            conflicts.append(f"{t}[{r}].{f}: {seen[cell]!r} vs {to!r}")
            continue
        seen[cell] = to
        try:
            rec = d[t] if r is None else d[t][int(r)]
        except (IndexError, ValueError, TypeError, KeyError):
            conflicts.append(f"bad record {t}[{r}]")
            continue
        if f not in rec:
            conflicts.append(f"{t}[{r}].{f} was not populated")
            continue
        rec[f] = to
    for t, idxs in deletes.items():
        if isinstance(d[t], list):
            d[t] = [rec for i, rec in enumerate(d[t]) if i not in idxs]
    return d, conflicts


# --------------------------------------------------------------------------- driver
LOG_DIR = HERE / "logs"


def _log(session: dict[str, Any]) -> None:
    """One file per LLM call: units sent (masked), feedback, raw reply, parsed reply or error."""
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = LOG_DIR / f"session_{session['run_id']}_{ts}_r{session['round']}.json"
    path.write_text(json.dumps(session, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _call(units, ctx: dict[str, str], cfg: Settings, feedback: str, show: bool,
          meta: dict[str, Any]) -> dict[str, Any]:
    payload = unit_payload(units, cfg)
    user = prompts.USER.format(units=dumps(payload), feedback=feedback,
                               today=datetime.now().date().isoformat(), **ctx)
    if show:
        print("=== SYSTEM ===\n" + prompts.SYSTEM + "\n=== USER ===\n" + user)
        return {}
    session = {**meta, "model": cfg.hf_model, "started_at": datetime.now().isoformat(timespec="seconds"),
               "units_sent": payload, "feedback": feedback or None, "raw_reply": None, "parsed": None, "error": None}
    try:
        session["raw_reply"] = ask(prompts.SYSTEM, user, cfg)
        session["parsed"] = parse_json(session["raw_reply"])
        return session["parsed"].get("units", {})
    except Exception as e:
        session["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        session["finished_at"] = datetime.now().isoformat(timespec="seconds")
        if cfg.session_log:
            _log(session)


def review(run_path: Path | str, cfg: Settings | None = None, print_prompt: bool = False,
           unit_ids: list[int] | None = None, trigger: str = "run") -> Path | None:
    """unit_ids: review only these units (e.g. after a UI re-run); results merge into the existing review file."""
    from load_rules import load_rules  # DAGRegistry/load_rules.py
    cfg = cfg or load_settings()
    run_path = Path(run_path)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    todo = [u for u in run["units"] if u["status"] == "needs_review"
            and (unit_ids is None or u["unit_id"] in unit_ids)]
    if not todo:
        return None
    registry = load_rules()
    count_dump = json.loads(cfg.count_dump.read_text(encoding="utf-8")) if cfg.count_dump.exists() else None
    blocked = feedback.blocked_values()
    ctx = {"rules": dumps(compact_rules(cfg, run.get("levels", []))), "count_rules": dumps(compact_counts(cfg)),
           "field_desc": cfg.field_desc.read_text(encoding="utf-8") if cfg.field_desc.exists() else "(none)",
           "blocked": "\n".join(f"{t}.{f}: {cur} -> {to}" for t, f, cur, to in sorted(blocked)) or "(none)"}

    results: dict[str, dict[str, Any]] = {}
    pending, retry_note = todo, ""  # not "feedback": that name is the imported module
    for rnd in range(1, cfg.max_rounds + 1):
        answers = _call(pending, ctx, cfg, retry_note, print_prompt,
                        {"run_id": run["run_id"], "run_file": run_path.name, "trigger": trigger, "round": rnd,
                         "attempts": {str(u["unit_id"]): u.get("attempts", 0) for u in pending}})
        if print_prompt:
            return None
        still, remaining = [], {}
        for u in pending:
            uid = str(u["unit_id"])
            a = answers.get(uid) or {}
            conv, cnt = a.get("conversions") or [], a.get("count_decisions") or []
            conv, rejected = _screen(u["draft"], conv, registry, blocked)
            fixed, conflicts = _apply(u["draft"], conv + cnt)
            left = _validate(fixed, registry, count_dump)
            results[uid] = {"unit_id": u["unit_id"], "key": u["key"], "rounds": rnd,
                            "attempts": u.get("attempts", 0), "trigger": trigger,
                            "conversions": conv, "count_decisions": cnt, "suggestions": a.get("suggestions") or [],
                            "rejected_conversions": rejected,
                            "conflicts": conflicts, "remaining_violations": left,
                            "status": "resolved" if not (left or conflicts) else "unresolved"}
            if left or conflicts:
                still.append(u)
                remaining[uid] = {"your_answer": a, "conflicts": conflicts, "still_failing": left,
                                  "rejected_conversions": rejected}
        if not still:
            break
        pending, retry_note = still, prompts.FEEDBACK.format(remaining=dumps(remaining))
    for r in results.values():
        if r["status"] == "unresolved":
            r["status"] = "skipped_conflict"  # not resolved within max_rounds: left for manual review

    out = run_path.parent / f"llm_review_{run['run_id']}.json"
    merged: dict[str, Any] = {}
    if out.exists():  # keep earlier units' reviews; replace only the units reviewed now
        merged = {str(u["unit_id"]): u for u in json.loads(out.read_text(encoding="utf-8")).get("units", [])}
    merged.update({str(k): v for k, v in results.items()})
    live = {str(u["unit_id"]) for u in run["units"]}
    out.write_text(json.dumps({
        "run_id": run["run_id"], "run_file": run_path.name, "model": cfg.hf_model,
        "reviewed_at": datetime.now().isoformat(timespec="seconds"), "withheld_fields": list(cfg.mask_fields),
        "units": sorted((v for k, v in merged.items() if k in live), key=lambda v: v["unit_id"])},
        indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    cfg = load_settings()
    path = Path(args[0]) if args else max(cfg.runs_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime)
    ids = [int(x) for x in opt["units"].split(",")] if opt.get("units") else None
    out = review(path, cfg, print_prompt="--print-prompt" in sys.argv, unit_ids=ids,
                 trigger=opt.get("trigger", "run"))
    print(out or "nothing to review / prompt printed")


if __name__ == "__main__":
    main()
