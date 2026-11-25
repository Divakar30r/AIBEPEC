"""Cumulative LLM feedback (LLMfeedback.json), collected once a run is FINISHED (every unit through, after the
user's corrections in the UI): value pairs = original value -> final value (LLM A) changes + user corrections),
count pairs = halted count state ("problem") and the finished state ("final").

The user weighs each pair in the UI (-1 never .. 0 no preference .. +1 always); the NEXT run uses them
(DataGenerator/weights.py) so the same pairs need no LLM call. Nothing here looks at the rule files -
pairs are purely what the LLM produced.

    python feedback.py <run_file>      # merge one run's LLM output into LLMfeedback.json

Merge: every pair is unique (see *_key). Weights of exactly -1 / +1 are never overwritten. Other text
value-pair weights are refreshed to the pair's share in the latest run (capped at AUTO_CAP, so only the user
sets +1). Number pairs and count pairs start at 0 and are left to the user.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PATH = HERE / "LLMfeedback.json"
AUTO_CAP = 0.9
REGISTRY_DUMP = HERE.parent / "DAGRegistry" / "registry_dump.json"


def _finite_lists(path: Path = REGISTRY_DUMP) -> dict[str, set[str]]:
    """'Table.Field' -> every value its ListStr branches allow (normalised), for fields with a finite list."""
    if not path.exists():
        return {}
    rules = json.loads(path.read_text(encoding="utf-8")).get("rules", {})
    return {ref: {norm(v) for b in r["branches"] if b["constraint"] == "ListStr" for v in b["allowed"]}
            for ref, r in rules.items() if any(b["constraint"] == "ListStr" for b in r["branches"])}
VALUE, COUNT = "Value-based", "Count-based"


def norm(v: Any) -> str:
    """Matching form of a value: case/space/punctuation-insensitive ("Tamil Nadu" == "TamilNadu")."""
    return re.sub(r"[^0-9a-z]", "", str(v).lower())


def value_key(r: dict[str, Any]) -> tuple:
    return (r["Table"], r["Field"], norm(r["current_value"]), str(r["LLM_value"]))


def count_key(r: dict[str, Any]) -> tuple:
    return (r["Field"], str(r["value"]), r["RelatedField"], str(r["RelatedFieldValue"]), int(r["Count"]))


def locked(r: dict[str, Any]) -> bool:
    return float(r.get("Weightage", 0)) in (-1.0, 1.0)


def load(path: Path = PATH) -> dict[str, list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not text:  # missing or cleared file = no feedback yet
        return {VALUE: [], COUNT: []}
    data = json.loads(text)
    for r in data.get(COUNT, []):  # accept the lowercase spelling too
        if "weightage" in r:
            r.setdefault("Weightage", r.pop("weightage"))
    for r in data.get(VALUE, []) + data.get(COUNT, []):
        r["Weightage"] = max(-1.0, min(1.0, float(r.get("Weightage", 0) or 0)))
    return {VALUE: data.get(VALUE, []), COUNT: data.get(COUNT, [])}


def save(data: dict[str, list[dict[str, Any]]], path: Path = PATH) -> None:
    """Writes unique pairs only (a later duplicate replaces an earlier one)."""
    out = {VALUE: list({value_key(r): r for r in data.get(VALUE, [])}.values()),
           COUNT: list({count_key(r): r for r in data.get(COUNT, [])}.values())}
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


# --------------------------------------------------------------------------- collect one run's pairs
def _rec(draft: dict[str, Any], table: str, record):
    data = draft.get(table)
    return data if record is None else data[int(record)]


def _type(v: Any) -> str:
    return "number" if isinstance(v, (int, float)) and not isinstance(v, bool) else "text"


def _final(draft: dict[str, Any], table: str, record, field: str):
    try:
        return _rec(draft, table, record).get(field)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def value_pairs(run: dict[str, Any]) -> tuple[list[dict[str, Any]], list[tuple]]:
    """Per changed cell of a finished unit: original value -> FINAL value (after the LLM's A) changes AND the
    user's corrections in the UI). Returns (pairs, overridden) - overridden = LLM pairs the user corrected."""
    out, overridden = [], []
    for u in run["units"]:
        events = sorted([{**e, "by": "LLM"} for e in u.get("llm_applied", [])] +
                        [{**e, "by": "UI"} for e in u.get("user_applied", [])], key=lambda e: e.get("attempt", 0))
        cells: dict[tuple, list[dict]] = {}
        for e in events:
            cells.setdefault((e["table"], e["record"], e["field"]), []).append(e)
        for (t, r, f), evs in cells.items():
            original, final = evs[0]["from"], _final(u["draft"], t, r, f)
            for e in evs:  # an LLM value the user changed afterwards was wrong for this value
                if e["by"] == "LLM" and str(e["to"]) != str(final):
                    overridden.append((t, f, norm(e["from"]), str(e["to"])))
            if final is None or original is None or str(original) == str(final):
                continue
            out.append({"Table": t, "Field": f, "Type": _type(original), "current_value": original,
                        "LLM_value": final, "Source": "UI" if any(e["by"] == "UI" for e in evs) else "LLM"})
    return out, overridden


def count_pairs(run: dict[str, Any], review: dict[str, Any] | None) -> list[dict[str, Any]]:
    """For units that halted on a count error: the halted state ("problem") and the finished unit's state
    ("final") as (parent field = value, related field = value, number of related records). The parent field
    each count depends on comes from the LLM's B) decisions (count_field -> parent_field)."""
    parent_of: dict[int, dict[str, str]] = {}
    for rv in (review or {}).get("units", []):
        for c in rv.get("count_decisions") or []:
            if c.get("count_field") and c.get("parent_field"):
                parent_of.setdefault(rv["unit_id"], {})[c["count_field"]] = c["parent_field"]
    out = []
    for u in run["units"]:
        pmap = parent_of.get(u["unit_id"], {})
        halts = u.get("halts", [])
        if not pmap or not halts:
            continue
        for h in halts:
            for v in h["count_violations"]:
                rel = f"{v['table']}.{v['field']}"
                pf = pmap.get(rel)
                if pf:
                    out.append({"RelatedTable": v["table"], "RelatedField": rel, "RelatedFieldValue": v["value"],
                                "Field": pf, "value": h["parent"].get(pf.split(".", 1)[1]), "Count": v["count"],
                                "Note": "problem"})
        prow = next((d for d in u["draft"].values() if isinstance(d, dict)), {})
        for rel, pf in pmap.items():
            t, _, f = rel.partition(".")
            recs = u["draft"].get(t)
            if not isinstance(recs, list):
                continue
            for val in sorted({str(r.get(f)) for r in recs if r.get(f) not in (None, "")}):
                out.append({"RelatedTable": t, "RelatedField": rel, "RelatedFieldValue": val, "Field": pf,
                            "value": prow.get(pf.split(".", 1)[1]),
                            "Count": sum(1 for r in recs if str(r.get(f)) == val), "Note": "final"})
    return out


def merge_run(run_path: Path | str, path: Path = PATH) -> dict[str, int]:
    """Merge a FINISHED run (every unit through, after the user's corrections) into the feedback list."""
    run_path = Path(run_path)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    rv_path = run_path.parent / f"llm_review_{run['run_id']}.json"
    review = json.loads(rv_path.read_text(encoding="utf-8")) if rv_path.exists() else None
    data = load(path)
    added = {"value_new": 0, "count_new": 0, "overridden": 0}

    # value pairs: share of each final value among all final values for the same (table, field, original value)
    vp, overridden = value_pairs(run)
    allowed = _finite_lists()
    # only text pairs whose current value is NOT already one of the field's allowed values
    # (numbers depend on context; an allowed value was changed for a dependency reason, not a bad value)
    vp = [p for p in vp if p["Type"] == "text"
          and norm(p["current_value"]) not in allowed.get(f"{p['Table']}.{p['Field']}", set())]
    totals: dict[tuple, int] = {}
    hits: dict[tuple, int] = {}
    for p in vp:
        totals[value_key(p)[:3]] = totals.get(value_key(p)[:3], 0) + 1
        hits[value_key(p)] = hits.get(value_key(p), 0) + 1
    index = {value_key(r): r for r in data[VALUE]}
    for k, n in hits.items():
        p = next(x for x in vp if value_key(x) == k)
        # numbers (ages, amounts) depend on context the pair doesn't carry: only the user weighs them
        share = round(min(AUTO_CAP, n / totals[k[:3]]), 2) if p["Type"] == "text" else 0.0
        r = index.get(k)
        if r is None:
            r = {**p, "Weightage": share, "Seen": 0}
            data[VALUE].append(r)
            index[k] = r
            added["value_new"] += 1
        elif not locked(r) and p["Type"] == "text":
            r["Weightage"] = share
        r["Seen"] = int(r.get("Seen", 0)) + n
        r["LastRun"] = run["run_id"]
    for k in set(overridden) - set(hits):  # the user corrected the LLM: that pair loses its (unlocked) weight
        r = index.get(k)
        if r is not None and not locked(r):
            r["Weightage"] = 0.0
            added["overridden"] += 1

    cindex = {count_key(r): r for r in data[COUNT]}
    for p in count_pairs(run, review):
        k = count_key(p)
        r = cindex.get(k)
        if r is None:
            r = {**p, "Weightage": 0.0, "Seen": 0}
            data[COUNT].append(r)
            cindex[k] = r
            added["count_new"] += 1
        r["Seen"] = int(r.get("Seen", 0)) + 1
        r["LastRun"] = run["run_id"]
    save(data, path)
    return added


def add_pair(section: str, row: dict[str, Any], unit: dict[str, Any] | None = None, path: Path = PATH) -> None:
    """Add (or update in place) one pair from the UI. `unit` = metadata of a unit removed with it (Never, -1),
    kept on the pair under "Units" so the removed data stays traceable."""
    data = load(path)
    key = value_key if section == VALUE else count_key
    rows = data[section]
    hit = next((r for r in rows if key(r) == key(row)), None)
    if hit is None:
        hit = dict(row)
        rows.append(hit)
    else:
        hit.update({k: v for k, v in row.items() if k not in ("Seen", "Units")})
    if unit is not None:
        hit.setdefault("Units", []).append(unit)
    save(data, path)


def blocked_values(path: Path = PATH) -> set[tuple]:
    """(table, field, norm(current), str(LLM value)) the user set to -1: never propose / apply."""
    return {value_key(r)[:3] + (str(r["LLM_value"]),) for r in load(path)[VALUE] if float(r["Weightage"]) == -1.0}


if __name__ == "__main__":
    print(merge_run(sys.argv[1]))
