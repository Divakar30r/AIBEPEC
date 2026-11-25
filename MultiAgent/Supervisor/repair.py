"""(B) Repair agent - no LLM call.

For halted units of one run, try to fix them by swapping WHOLE related-table sets (all child records of a
unit) between halted units at the same level, re-keyed to the new parent. Completed units never take part.

  feasible(i, j)  unit i's parent + unit j's child set passes every rule checked so far (field + count rules)
  assignment      maximum bipartite matching (Kuhn) units -> child sets; preference order per unit comes from
                  positive count pairs in LLMfeedback.json (the human-approved feedback = shared memory)
  leftovers       units that can't be fixed keep their own set when it is still free, else take a leftover
                  set - every set stays with exactly one unit
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import ROOT  # noqa: F401  (sets sys.path)
import generator  # noqa: E402
import weights as fb_weights  # noqa: E402
from schema import build_plan  # noqa: E402
from settings import Config  # noqa: E402


def _trial(cfg: Config, parent_unit: dict[str, Any], donor_unit: dict[str, Any]) -> dict[str, Any]:
    draft = {cfg.parent: dict(parent_unit["draft"][cfg.parent])}
    for child, c in cfg.children.items():
        kf = c.get("key_field", cfg.key_field)
        draft[child] = [{**r, kf: parent_unit["key"]} for r in donor_unit["draft"].get(child, [])]
    return draft


def _score(w, cfg: Config, draft: dict[str, Any]) -> float:
    """Agreement with user-weighted count pairs (positive weights only): higher = preferred."""
    if not w:
        return 0.0
    s = 0.0
    for related, pairs in list(w.counts.items()) + list(w.only.items()) + list(w.maxp.items()):
        t, _, f = related.partition(".")
        recs = draft.get(t)
        if not isinstance(recs, list):
            continue
        for p in pairs:
            wt = float(p.get("_share", p["Weightage"]))  # Only/Max Possibility pairs score with their share
            if wt > 0 and w._parent_matches(draft, cfg.parent, p):
                n = sum(1 for r in recs if str(r.get(f)) == str(p["RelatedFieldValue"]))
                if (n <= int(p["Count"])) if fb_weights.is_max(p) else (n == int(p["Count"])):
                    s += wt
    return s


def _match(units: list[int], options: dict[int, list[int]]) -> dict[int, int]:
    """Kuhn's maximum bipartite matching: unit -> donor (child set owner)."""
    owner: dict[int, int] = {}  # donor -> unit

    def try_assign(u: int, seen: set[int]) -> bool:
        for d in options[u]:
            if d in seen:
                continue
            seen.add(d)
            if d not in owner or try_assign(owner[d], seen):
                owner[d] = u
                return True
        return False

    for u in units:
        try_assign(u, set())
    return {u: d for d, u in owner.items()}


def plan_swaps(run_path: Path | str, cfg: Config) -> dict[str, Any]:
    """Compute the best swap per halted level. Returns {"assignment": {unit: donor}, "fixable": [...], ...}."""
    data = json.loads(Path(run_path).read_text(encoding="utf-8"))
    plan, registry = build_plan(cfg), generator.load_rules()
    try:
        w = fb_weights.load_weights()
    except Exception:
        w = None
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for u in data["units"]:
        if u["status"] == "needs_review" and u.get("halted_before_level") is not None:
            groups[int(u["halted_before_level"])].append(u)
    assignment: dict[int, int] = {}
    fixable: list[int] = []
    checked = 0
    for level, us in groups.items():
        if len(us) < 2:
            continue
        ids = [u["unit_id"] for u in us]
        by = {u["unit_id"]: u for u in us}
        options: dict[int, list[int]] = {}
        for i in ids:
            ok = []
            for j in ids:
                trial = _trial(cfg, by[i], by[j])
                checked += 1
                if not generator.check_all(registry, cfg, plan, trial, level):
                    ok.append((_score(w, cfg, trial), j != i, j))  # prefer feedback score, then a real swap
            options[i] = [j for _, _, j in sorted(ok, key=lambda x: (-x[0], not x[1]))]
        matched = _match(ids, options)
        free = [d for d in ids if d not in matched.values()]
        for i in ids:  # unmatched units: own set if still free, else a leftover set
            if i not in matched:
                matched[i] = i if i in free else free[0]
                free.remove(matched[i])
        fixable += [i for i in ids if i in options and matched[i] in options[i]]
        assignment.update({i: d for i, d in matched.items() if i != d})
    return {"assignment": assignment, "fixable": sorted(fixable), "groups": {k: len(v) for k, v in groups.items()},
            "checked": checked}


def run_repair(run_path: Path | str, cfg: Config) -> dict[str, Any]:
    """Plan and apply the swaps (only if at least one unit becomes valid). Returns a summary."""
    p = plan_swaps(run_path, cfg)
    applied: dict[int, str] = {}
    if p["fixable"] and p["assignment"]:
        applied = generator.swap_child_sets(run_path, p["assignment"], cfg)
    return {**p, "applied": applied}
