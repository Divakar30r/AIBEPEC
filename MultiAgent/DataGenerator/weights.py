"""User-weighted LLM feedback (../LLMEffects/LLMfeedback.json) applied while generating a NEW run.

Weightage: -1 never .. 0 no preference .. +1 always. Fractions are approximate by design.
Priority: the order of the pairs in the file (set by dragging in the UI) - earlier pairs are considered first.
Value pairs act while a field is filled; count pairs act after that, once the level's records exist.

Value pairs  (table, field, current value -> LLM value), applied when a source (CSV) value is copied in:
  positive weights are shares - e.g. Familyfloat -> CI 0.3 converts ~30% of such values with no LLM call;
  the rest keep the source value (and go to the LLM if they break a rule). Negative pairs are never applied
  (-1 pairs are also forbidden to the LLM, see LLMEffects/review.py).

Count pairs  (parent field = value, related field = value, Count), applied right after the related field is
filled for all records of a unit:
  positive w: with probability w, make exactly Count related records carry that value;
  negative w: with probability |w|, keep fewer than Count of them - the surplus records are re-picked from
  the other values (rule options of that record, else other non-negative count pairs). If nothing else is
  possible the records are left as they are and the rules stop the unit as usual.
Nothing here enforces the rule files; the weights are taken as the user set them.
"""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from typing import Any, Callable

FEEDBACK_PY = Path(__file__).resolve().parent.parent / "LLMEffects" / "feedback.py"


def _feedback_module():
    """LLMEffects/feedback.py loaded by path (LLMEffects shares module names like settings.py with us)."""
    spec = importlib.util.spec_from_file_location("llm_feedback", FEEDBACK_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Weights:
    def __init__(self, data: dict[str, list[dict[str, Any]]], norm: Callable[[Any], str]):
        self.norm = norm
        self.values: dict[tuple, list[tuple[Any, float, str]]] = {}
        for r in data.get("Value-based", []):
            w = float(r.get("Weightage", 0))
            if w > 0:
                to = r["LLM_value"]
                if r.get("Type") == "number":
                    try:
                        to = int(to) if float(to).is_integer() else float(to)
                    except (TypeError, ValueError):
                        pass
                self.values.setdefault((r["Table"], r["Field"], norm(r["current_value"])), []).append(
                    (to, w, str(r["LLM_value"])))
        self.counts: dict[str, list[dict[str, Any]]] = {}
        for r in data.get("Count-based", []):
            if float(r.get("Weightage", 0)) != 0:
                self.counts.setdefault(r["RelatedField"], []).append(r)

    def __bool__(self) -> bool:
        return bool(self.values or self.counts)

    # ------------------------------------------------------------------ value pairs
    def remap(self, table: str, fld: str, value: Any, rng: random.Random) -> tuple[Any, str | None]:
        """(value to store, note or None). +1 always wins; otherwise positive weights are shares."""
        cands = self.values.get((table, fld, self.norm(value)))
        if not cands:
            return value, None
        sure = [c for c in cands if c[1] >= 1]  # the highest-priority +1 wins
        pick = sure[0] if sure else None
        if pick is None:
            r, acc = rng.random(), 0.0
            for c in cands:  # priority order (file order): earlier pairs claim their share first
                acc += c[1]
                if r < acc:
                    pick = c
                    break
        if pick is None:
            return value, None
        return pick[0], f"{table}.{fld}: {value!r} -> {pick[0]!r} (weighted feedback {pick[1]:g}, no LLM call)"

    # ------------------------------------------------------------------ count pairs
    def adjust_counts(self, draft: dict[str, Any], parent: str, table: str, fld: str,
                      options: Callable[[dict[str, Any]], list[Any]], rng: random.Random) -> list[str]:
        """Steer how many records of `table` carry each value of `fld`. Returns notes."""
        pairs = [p for p in self.counts.get(f"{table}.{fld}", []) if self._parent_matches(draft, parent, p)]
        recs = draft.get(table)
        if not pairs or not isinstance(recs, list):
            return []
        notes, pinned = [], set()
        avoid = {str(p["RelatedFieldValue"]) for p in pairs if float(p["Weightage"]) < 0}

        def holders(v):
            return [i for i, r in enumerate(recs) if str(r.get(fld)) == str(v)]

        def repick(i: int, not_value: str) -> bool:
            alts = [a for a in options(recs[i]) if str(a) != not_value and str(a) not in avoid]
            alts = alts or [p["RelatedFieldValue"] for p in pairs
                            if float(p["Weightage"]) >= 0 and str(p["RelatedFieldValue"]) != not_value]
            if not alts:
                return False
            recs[i][fld] = rng.choice(alts)
            return True

        for p in pairs:  # priority order (file order)
            w, v, c = float(p["Weightage"]), p["RelatedFieldValue"], int(p["Count"])
            if rng.random() >= abs(w):
                continue
            have = holders(v)
            if w > 0:
                if len(have) < c:
                    free = [i for i in range(len(recs)) if i not in have and i not in pinned]
                    for i in rng.sample(free, min(len(free), c - len(have))):
                        recs[i][fld] = v
                elif len(have) > c:
                    for i in [i for i in have if i not in pinned][: len(have) - c]:
                        repick(i, str(v))
                pinned.update(holders(v))
                notes.append(f"{table}.{fld}: {len(holders(v))} x {v!r} (weighted feedback {w:g}: "
                             f"{p['Field']}={p['value']!r} -> {c})")
            elif len(have) >= c:
                surplus = [i for i in have if i not in pinned][: len(have) - c + 1]
                moved = sum(repick(i, str(v)) for i in surplus)
                notes.append(f"{table}.{fld}: avoided {c} x {v!r} under {p['Field']}={p['value']!r} "
                             f"(weighted feedback {w:g}; re-picked {moved}/{len(surplus)})")
        return notes

    @staticmethod
    def _parent_matches(draft: dict[str, Any], parent: str, p: dict[str, Any]) -> bool:
        t, _, f = str(p["Field"]).partition(".")
        row = draft.get(t)
        return t == parent and isinstance(row, dict) and str(row.get(f)) == str(p["value"])


def load_weights() -> Weights | None:
    if not FEEDBACK_PY.exists():
        return None
    mod = _feedback_module()
    w = Weights(mod.load(), mod.norm)
    return w or None


def merge_run(run_path: Path | str) -> dict[str, int]:
    """Collect this run's A/B LLM output into the cumulative LLMfeedback.json."""
    return _feedback_module().merge_run(run_path)


def load_feedback() -> dict[str, list[dict[str, Any]]]:
    return _feedback_module().load()


def save_feedback(data: dict[str, list[dict[str, Any]]]) -> None:
    _feedback_module().save(data)


def add_pair(section: str, row: dict[str, Any], unit: dict[str, Any] | None = None) -> None:
    _feedback_module().add_pair(section, row, unit)
