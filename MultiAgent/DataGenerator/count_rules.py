"""Count-rule checks from DAGRegistry/count_dump.json.

A rule limits how many records of `counts_records_of` may have target == value.
Per combination:
  * conditions on another table (e.g. the parent) decide whether the combination applies;
  * conditions on the counted table itself filter which records are counted;
  * count {min, max}; allowed=false means max 0.
No matching combination -> no limit. If any matching combination disallows, it wins.

A rule is checked only once every field in its involved_fields has been attempted
(its level has been generated), and a condition on a blank value never matches.
"""
from __future__ import annotations

from typing import Any

Draft = dict[str, Any]


def _split(ref: str) -> tuple[str, str]:
    table, _, fld = ref.partition(".")
    return table, fld


def _filled(v: Any) -> bool:
    return v is not None and v != ""


def _match(cond: dict[str, Any], v: Any) -> bool:
    return _filled(v) and (cond.get("any") or str(v) in [str(x) for x in cond.get("in", [])])


def _records(draft: Draft, table: str) -> list[tuple[int | None, dict[str, Any]]]:
    data = draft.get(table)
    if data is None:
        return []
    return [(None, data)] if isinstance(data, dict) else list(enumerate(data))


def _cond_text(when: dict[str, Any]) -> str:
    return ", ".join(f"{k} {'any' if c.get('any') else 'in ' + str(c['in'])}" for k, c in when.items()) or "always"


def check_counts(dump: dict[str, Any] | None, draft: Draft, attempted: set[str]) -> list[dict[str, Any]]:
    if not dump:
        return []
    out: list[dict[str, Any]] = []
    for r in dump["rules"]:
        if not set(r["involved_fields"]) <= attempted:
            continue  # not all values have been attempted yet
        table, fld = _split(r["target"])
        recs = _records(draft, r.get("counts_records_of", table))
        matched = []
        for c in r["combinations"]:
            applies, filters = True, []
            for ref, cond in c["when"].items():
                t, f = _split(ref)
                if t == table:
                    filters.append((f, cond))
                elif not any(_match(cond, rec.get(f)) for _, rec in _records(draft, t)):
                    applies = False
                    break
            if not applies:
                continue
            pool = [(i, rec) for i, rec in recs if all(_match(cond, rec.get(f)) for f, cond in filters)]
            hits = [i for i, rec in pool if rec.get(fld) == r["value"]]
            matched.append((c, pool, hits))
        disallow = [m for m in matched if not m[0]["allowed"]]
        for c, pool, hits in (disallow or matched):
            lo, hi = c["count"]["min"], c["count"]["max"]
            if lo <= len(hits) <= hi:
                continue
            too_many = len(hits) > hi
            out.append({
                "kind": "count", "table": table, "field": fld, "record": None, "value": r["value"],
                "count": len(hits), "allowed_count": [lo, hi],
                # records a reviewer could change: the offending ones, or the candidates when too few
                "records": hits if too_many else [i for i, _ in pool if i not in hits],
                "reason": (f"{len(hits)} record(s) with {fld}={r['value']!r}; allowed {lo}..{hi} "
                           f"when {_cond_text(c['when'])}"),
            })
            break  # one error per rule is enough
    return out
