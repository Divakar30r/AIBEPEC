"""Count rules (../PolRefCount.json) -> normalized dump (count_dump.json).

Rule shape:
    {"Table": T, "Field": F, "Value": V,
     "Combination": [ {<qualified field>: [values], ..., "Count": [min, max] | 0}, ... ]}

Meaning: how many records of table T may have F == V, under each combination.
  * keys other than "Count" are conditions; several keys in one combination are AND-ed
  * ["*"] = any value; ["A1","B1"] or ["A1,B1"] = value must be one of them (comma lists are split)
  * "Count": [min, max] -> allowed range; 0 -> combination not allowed (stored as [0, 0])
  * condition fields are already fully qualified (Table.Field, or Table.JSONB.path) and are
    used exactly as written - they may point at any table. "Table" qualifies only "Field".
  * involved_fields (per combination, per rule, and per target) = condition fields + the target
    itself: the generator applies a rule only once all of them are populated
  * no matching combination -> allowed (no limit); overlapping matches -> a disallow (0) wins

    python load_count_rules.py    # writes count_dump.json next to this file
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_PATH = HERE.parent / "PolRefCount.json"
OUT_PATH = HERE / "count_dump.json"


class CountRuleError(ValueError):
    pass


def _values(raw: Any) -> list[str] | None:
    """None = any value ('*'); otherwise the flattened list of allowed values."""
    items = raw if isinstance(raw, list) else [raw]
    flat = [v.strip() for item in items for v in str(item).split(",") if v.strip()]
    if not flat:
        raise CountRuleError(f"empty value list: {raw!r}")
    return None if "*" in flat else flat


def _count(raw: Any) -> list[int]:
    if isinstance(raw, list):
        if len(raw) != 2 or not all(isinstance(x, int) for x in raw) or not 0 <= raw[0] <= raw[1]:
            raise CountRuleError(f"Count must be [min, max] with 0 <= min <= max: {raw!r}")
        return list(raw)
    if raw == 0 and not isinstance(raw, bool):
        return [0, 0]  # not-allowed combination
    raise CountRuleError(f"Count must be [min, max] or 0 (not allowed): {raw!r}")


def build_dump(raw: list[dict[str, Any]], version: str) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for i, r in enumerate(raw):
        for k in ("Table", "Field", "Value", "Combination"):
            if k not in r:
                raise CountRuleError(f"rule #{i} is missing {k!r}: {r}")
        table = r["Table"]
        combos, deps = [], set()
        for j, c in enumerate(r["Combination"]):
            if "Count" not in c:
                raise CountRuleError(f"rule #{i} combination #{j} has no Count")
            conds = {}
            for k, v in c.items():
                if k == "Count":
                    continue
                ref = k  # fully qualified in the source; never prefixed
                vals = _values(v)
                conds[ref] = {"any": True} if vals is None else {"in": vals}
                deps.add(ref)
            cnt = _count(c["Count"])
            target = f"{table}.{r['Field']}"
            combos.append({"when": conds, "count": {"min": cnt[0], "max": cnt[1]}, "allowed": cnt[1] > 0,
                           # fields that must be populated before this combination can be checked
                           "involved_fields": sorted(set(conds) | {target})})
        target = f"{table}.{r['Field']}"
        rules.append({
            "target": target, "value": r["Value"], "counts_records_of": table,
            "depends_on": sorted(deps),
            # union over all combinations: once these are populated the whole rule can be applied
            "involved_fields": sorted(deps | {target}),
            "combinations": combos,
        })
    return {"version": version, "source": "PolRefCount.json",
            "semantics": {"no_match": "allowed", "overlap": "disallow (count 0) takes precedence",
                          "conditions": "AND within a combination"},
            "involved_fields_by_target": _by_target(rules),
            "rules": rules}


def _by_target(rules: list[dict[str, Any]]) -> dict[str, list[str]]:
    """target field -> every field any of its rules needs; lets the generator check readiness per field."""
    out: dict[str, set[str]] = {}
    for r in rules:
        out.setdefault(r["target"], set()).update(r["involved_fields"])
    return {t: sorted(fs) for t, fs in sorted(out.items())}


def main(path: Path = DEFAULT_PATH) -> None:
    data = path.read_bytes()
    dump = build_dump(json.loads(data), hashlib.sha256(data).hexdigest()[:12])
    OUT_PATH.write_text(json.dumps(dump, indent=2), encoding="utf-8")
    print(f"version={dump['version']} rules={len(dump['rules'])} -> {OUT_PATH}")


if __name__ == "__main__":
    main()
