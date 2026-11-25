"""User-weighted LLM feedback (../LLMEffects/LLMfeedback.json) applied while generating a NEW run.

Weightage: -1 never .. 0 no preference .. +1 always. Fractions are approximate by design.
Priority: the order of the pairs in the file (set by dragging in the UI) - earlier pairs are considered first.
Value pairs act while a field is filled; count pairs act after that, once the level's records exist.

Value pairs  (table, field, current value -> LLM value), applied when a source (CSV) value is copied in:
  positive weights are shares - e.g. Familyfloat -> CI 0.3 converts ~30% of such values with no LLM call;
  the rest keep the source value (and go to the LLM if they break a rule). Negative pairs are never applied
  (-1 pairs are also forbidden to the LLM, see LLMEffects/review.py). "Option": "Archive" only hides a value
  pair in the UI's list - it is still applied here, at its priority.

Count pairs  (parent field = value, related field = value, Count), applied right after the related field is
filled for all records of a unit:
  positive w: with probability w, make exactly Count related records carry that value;
  negative w: with probability |w|, keep fewer than Count of them - the surplus records are re-picked from
  the other values (rule options of that record, else other non-negative count pairs). If nothing else is
  possible the records are left as they are and the rules stop the unit as usual.

'Only Possibility' count pairs (Options column in the UI, stored as "Option") - "Prediction not enforcement":
  the pair's own Weightage is not used. Its share is PREDICTED from the value pairs that convert INTO the
  pair's parent value: e.g. PolicyType senior_citizen -> CI 0.3 and individual -> CI 0.2 give 0.5 for
  PolicyType = CI, so ~50% of the CI units get exactly Count records with that value (others re-picked).
  They are applied before the weighted count pairs; once applied, no other pair changes that value's count.
  Raising the value weights towards 1 makes it apply to every such unit - still no hard rule.
'Max Possibility' count pairs - same idea for an OPTIONAL value: AT MOST Count records carry it (0 is fine; extra
  records are re-picked, none are ever added). Share = the predicted share of the parent value x the pair's own
  Weightage: CI predicted 0.5 and SPS weight 0.3 -> ~15% of the CI units get at most 1 SPS.
One draw per unit and parent value (e.g. PolicyType = CI) serves all its Only/Max pairs, so they apply
together, and the Max units are a subset of the Only units. Adding a value never takes a record whose value
has its own 'Only Possibility' pair. Each applied pair leaves a hedged ("probably due to") note on the unit.
Nothing here enforces the rule files; the weights are taken as the user set them.
"""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from typing import Any, Callable

FEEDBACK_PY = Path(__file__).resolve().parent.parent / "LLMEffects" / "feedback.py"
ONLY = "Only Possibility"  # values of a count pair's "Option"
MAX = "Max Possibility"


def option(pair: dict[str, Any]) -> str | None:
    o = str(pair.get("Option") or "")
    return o if o in (ONLY, MAX) else None


def is_only(pair: dict[str, Any]) -> bool:
    return option(pair) == ONLY


def is_max(pair: dict[str, Any]) -> bool:
    return option(pair) == MAX


def predicted_share(values: list[dict[str, Any]], pair: dict[str, Any], norm: Callable[[Any], str]) -> tuple[float, int]:
    """(share, number of value pairs) of an Only/Max count pair's parent value: the sum of the positive weights of
    the value pairs whose LLM value is the pair's parent value (same table/field), capped at 1."""
    t, _, f = str(pair["Field"]).partition(".")
    ws = [float(r.get("Weightage") or 0) for r in values
          if r.get("Table") == t and r.get("Field") == f and norm(r.get("LLM_value")) == norm(pair.get("value"))]
    ws = [w for w in ws if w > 0]
    return min(1.0, sum(ws)), len(ws)


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
        self.only: dict[str, list[dict[str, Any]]] = {}  # 'Only Possibility' pairs, with "_share"
        self.maxp: dict[str, list[dict[str, Any]]] = {}  # 'Max Possibility' pairs, with "_share"
        for r in data.get("Count-based", []):
            opt = option(r)
            if opt:
                base, n = predicted_share(data.get("Value-based", []), r, norm)
                share = base if opt == ONLY else base * max(0.0, float(r.get("Weightage") or 0))
                if share > 0:
                    (self.only if opt == ONLY else self.maxp).setdefault(r["RelatedField"], []).append(
                        {**r, "_share": share, "_base": base, "_from": n})
            elif float(r.get("Weightage", 0)) != 0:
                self.counts.setdefault(r["RelatedField"], []).append(r)

    def __bool__(self) -> bool:
        return bool(self.values or self.counts or self.only or self.maxp)

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
                      options: Callable[[dict[str, Any]], list[Any]], rng: random.Random,
                      draws: dict[tuple, float] | None = None) -> list[str]:
        """Steer how many records of `table` carry each value of `fld`. Returns notes.
        `draws`: the unit's draws per parent value, shared across levels (one dict per unit)."""
        key = f"{table}.{fld}"
        pairs = [p for p in self.counts.get(key, []) if self._parent_matches(draft, parent, p)]
        onlys = [p for p in self.only.get(key, []) if self._parent_matches(draft, parent, p)]
        maxes = [p for p in self.maxp.get(key, []) if self._parent_matches(draft, parent, p)]
        recs = draft.get(table)
        if not (pairs or onlys or maxes) or not isinstance(recs, list):
            return []
        draws = {} if draws is None else draws
        notes, pinned = [], set()
        fixed: set[str] = set()  # values whose count an 'Only Possibility' pair set in this unit
        cap: dict[str, int] = {}  # value -> at most this many ('Max Possibility' applied in this unit)
        protect = {str(p["RelatedFieldValue"]) for p in onlys}  # never overwritten when a value is added
        avoid = {str(p["RelatedFieldValue"]) for p in pairs if float(p["Weightage"]) < 0}

        def holders(v):
            return [i for i, r in enumerate(recs) if str(r.get(fld)) == str(v)]

        def free_for(v) -> list[int]:
            return [i for i in range(len(recs)) if str(recs[i].get(fld)) != str(v) and i not in pinned
                    and str(recs[i].get(fld)) not in protect]

        def blocked(a) -> bool:
            a = str(a)
            return a in avoid or a in fixed or (a in cap and len(holders(a)) >= cap[a])

        def repick(i: int, not_value: str) -> bool:
            alts = [a for a in options(recs[i]) if str(a) != not_value and not blocked(a)]
            alts = alts or [p["RelatedFieldValue"] for p in pairs if float(p["Weightage"]) >= 0
                            and str(p["RelatedFieldValue"]) != not_value and not blocked(p["RelatedFieldValue"])]
            if not alts:
                return False
            recs[i][fld] = rng.choice(alts)
            return True

        def drawn(p) -> bool:
            """One draw per unit and parent value for all its Only/Max pairs (Max units within the Only units)."""
            return draws.setdefault((str(p["Field"]), str(p["value"])), rng.random()) < float(p["_share"])

        for p in onlys:  # 'Only Possibility' first - predicted share, not enforcement
            v, c, s = p["RelatedFieldValue"], int(p["Count"]), float(p["_share"])
            if str(v) in fixed or not drawn(p):
                continue
            have = holders(v)
            if len(have) < c:
                free = free_for(v)
                for i in rng.sample(free, min(len(free), c - len(have))):
                    recs[i][fld] = v
            elif len(have) > c:
                for i in [i for i in have if i not in pinned][: len(have) - c]:
                    repick(i, str(v))
            fixed.add(str(v))
            pinned.update(holders(v))
            # hedged: the same count may well have come out without this pair
            notes.append(f"{table}.{fld}: {len(holders(v))} x {v!r} - probably due to '{ONLY}' "
                         f"({p['Field']}={p['value']!r} -> {c} x {v!r}; predicted share {s:.2f} "
                         f"from {p['_from']} value pair{'s' if p['_from'] != 1 else ''})")

        for p in maxes:  # 'Max Possibility': at most Count - extras re-picked, nothing added
            v, c, s = p["RelatedFieldValue"], int(p["Count"]), float(p["_share"])
            if str(v) in fixed or str(v) in cap or not drawn(p):
                continue
            had = holders(v)
            cap[str(v)] = c
            for i in [i for i in had if i not in pinned][: max(0, len(had) - c)]:
                repick(i, str(v))
            if had:  # nothing to say when the unit has none of it
                notes.append(f"{table}.{fld}: {len(holders(v))} x {v!r} (at most {c}) - probably due to '{MAX}' "
                             f"({p['Field']}={p['value']!r} -> at most {c} x {v!r}; share {s:.2f} = predicted "
                             f"{float(p['_base']):.2f} x weight {float(p['Weightage']):.2f})")

        for p in pairs:  # priority order (file order)
            w, v, c = float(p["Weightage"]), p["RelatedFieldValue"], int(p["Count"])
            if str(v) in fixed or str(v) in cap or rng.random() >= abs(w):
                continue
            have = holders(v)
            if w > 0:
                if len(have) < c:
                    free = free_for(v)
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
