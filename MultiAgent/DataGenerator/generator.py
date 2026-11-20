"""Generate draft policy units level by level (topological levels of the rule DAG).

Per unit (one primary key and all its related table records), per level:
  validate drafts so far -> stop the unit for manual review on any violation
  -> fill this level's fields:  B) copy from XLSource (CSV exact matches)
                                C) pick from the registry's allowed values / range
                                D) Faker
Units run in parallel; a halted unit does not affect the others. Nothing is written to a database.

    python generator.py [--units N] [--seed S]
"""
from __future__ import annotations

import argparse
import json
import random
import string
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from faker import Faker

from schema import Branch, Node, Plan, build_plan
from settings import Config, load_config
from source import load_xlsource

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "DAGRegistry"))
from load_rules import _shift, _to_date, load_rules, parse_range_c  # noqa: E402  (authoritative validator)

Draft = dict[str, Any]  # {parent: {..}, child: [{..}, ..]}


@dataclass
class Unit:
    unit_id: int
    key: str
    draft: Draft
    status: str = "running"  # completed | needs_review | error
    halted_before_level: int | None = None
    levels_done: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Value generation
# --------------------------------------------------------------------------- #
def faker_value(spec: str, fake: Faker, rng: random.Random) -> Any:
    name, *args = spec.split(":")
    if name == "random_element":
        return rng.choice(args[0].split(","))
    if name == "random_int":
        return rng.randint(int(args[0]), int(args[1]))
    if name == "future_date":
        return fake.future_date(end_date=args[0] if args else "+1y").isoformat()
    return getattr(fake, name)(*args)


def applicable(branches: tuple[Branch, ...], ctx: dict[str, dict[str, Any]]) -> list[Branch]:
    return [b for b in branches if all(ctx.get(t, {}).get(f) == v for (t, f), v in b.guards)]


def value_from_branch(b: Branch, ctx: dict[str, dict[str, Any]], table: str, rng: random.Random) -> Any:
    if b.constraint == "ListStr":
        return rng.choice(b.allowed)
    if b.constraint == "RangeInt":
        return rng.randint(*b.allowed)
    if b.constraint == "Range_YYYYMM":
        lo, hi = b.allowed
        months = [y * 100 + m for y in range(lo // 100, hi // 100 + 1) for m in range(1, 13) if lo <= y * 100 + m <= hi]
        return rng.choice(months)
    if b.constraint == "Range_C":
        ast = parse_range_c(b.allowed, table)
        ref = ctx.get(ast.ref[0], {}).get(ast.ref[1])
        if ref is None:
            raise LookupError(f"{ast.ref[0]}.{ast.ref[1]} not filled yet")
        r = _to_date(ref)
        if ast.op in (">", ">="):
            return (_shift(r, ast.unit, ast.magnitude) + timedelta(days=rng.randint(0, 365))).isoformat()
        if ast.op in ("<", "<="):
            return (_shift(r, ast.unit, -ast.magnitude) - timedelta(days=rng.randint(0, 365))).isoformat()
        return _shift(r, ast.unit, ast.magnitude).isoformat()
    raise ValueError(b.constraint)


# --------------------------------------------------------------------------- #
# Validation (against the DAG registry built from PolRef.json)
# --------------------------------------------------------------------------- #
def validate(registry, cfg: Config, draft: Draft) -> list[dict[str, Any]]:
    parent = cfg.parent
    out: list[dict[str, Any]] = []

    def add(v, record: int | None) -> None:
        out.append({"table": v.table, "field": v.field, "record": record, "value": v.value, "reason": v.reason})

    for v in registry.validate_row({parent: draft[parent]}):
        if v.table == parent:
            add(v, None)
    for child in cfg.children:
        for i, rec in enumerate(draft[child]):
            for v in registry.validate_row({parent: draft[parent], child: rec}):
                if v.table == child:
                    add(v, i)
    return out


# --------------------------------------------------------------------------- #
# One unit
# --------------------------------------------------------------------------- #
def new_key(rng: random.Random, cfg: Config, used: set[str]) -> str:
    while True:
        k = "".join(rng.choices(string.ascii_uppercase + string.digits, k=cfg.key_length))
        if k not in used:
            used.add(k)
            return k


def _advance(unit: Unit, start_lvl: int, cfg: Config, plan: Plan, registry, xlsource: list[dict[str, Any]],
             rng: random.Random, fake: Faker) -> Unit:
    """Validate-then-fill each level from start_lvl; halts the unit on the first violation."""
    parent, draft = cfg.parent, unit.draft
    source_row: dict[tuple[str, int], dict[str, Any]] = {}  # one XLSource row per record keeps name/age coherent

    def records(table: str) -> list[tuple[int | None, dict[str, Any]]]:
        return [(None, draft[table])] if table == parent else list(enumerate(draft[table]))

    try:
        for lvl in range(start_lvl, len(plan.levels)):
            nodes = plan.levels[lvl]
            if lvl > 0:
                unit.violations = validate(registry, cfg, draft)
                if unit.violations:
                    unit.status, unit.halted_before_level = "needs_review", lvl
                    return unit
            for table, fld in nodes:
                target = f"{table}.{fld}"
                for idx, rec in records(table):
                    ctx = {parent: draft[parent], table: rec}
                    src = source_row.setdefault((table, idx or 0), rng.choice(xlsource) if xlsource else {})
                    if target in src:                                               # B) CSV
                        rec[fld] = src[target]
                    elif (table, fld) in plan.rules:                                # C) rule
                        options = applicable(plan.rules[(table, fld)], ctx)
                        if not options:
                            unit.notes.append(f"{target}: no rule branch applies to current values - left blank")
                            continue
                        rec[fld] = value_from_branch(rng.choice(options), ctx, table, rng)
                    else:                                                           # D) Faker
                        rec[fld] = faker_value(cfg.faker.get(target, cfg.faker_default), fake, rng)
            unit.levels_done = lvl + 1
        unit.violations = validate(registry, cfg, draft)  # final check after the last level
        unit.status = "needs_review" if unit.violations else "completed"
        unit.halted_before_level = len(plan.levels) if unit.violations else None
    except Exception as e:  # keep other units running
        unit.status = "error"
        unit.notes.append(f"{type(e).__name__}: {e}")
    return unit


def _rngs(cfg: Config, seed: int | None, unit_id: int, attempt: int = 0) -> tuple[random.Random, Faker]:
    s = None if seed is None else seed * 100003 + unit_id + attempt * 7919
    fake = Faker(cfg.faker_locale)
    if s is not None:
        fake.seed_instance(s)
    return random.Random(s), fake


def run_unit(unit_id: int, key: str, cfg: Config, plan: Plan, registry, xlsource: list[dict[str, Any]],
             seed: int | None) -> Unit:
    rng, fake = _rngs(cfg, seed, unit_id)
    # A) primary key on every record of the unit; record counts per child table.
    draft: Draft = {cfg.parent: {cfg.key_field: key}}
    for child, c in cfg.children.items():
        n = rng.randint(c["min_per_key"], c["max_per_key"])
        draft[child] = [{c.get("key_field", cfg.key_field): key} for _ in range(n)]
    return _advance(Unit(unit_id, key, draft), 0, cfg, plan, registry, xlsource, rng, fake)


def rerun_unit(u: dict[str, Any], fixes: list[dict[str, Any]], cfg: Config, plan: Plan, registry,
               xlsource: list[dict[str, Any]], seed: int | None = None) -> dict[str, Any]:
    """Apply manual corrections to a halted unit and resume from the level it stopped before.

    u is a unit dict as stored in a run file. fixes: [{"table", "record", "field", "value"}].
    Levels already filled are kept; only the remaining levels are (re)generated.
    """
    if u["status"] != "needs_review" or u["halted_before_level"] is None:
        raise ValueError(f"unit {u['unit_id']} is not halted for review")
    draft = json.loads(json.dumps(u["draft"]))  # deep copy
    for f in fixes:
        rec = draft[f["table"]] if f["record"] is None else draft[f["table"]][f["record"]]
        rec[f["field"]] = f["value"]
    attempt = int(u.get("attempts", 0)) + 1
    start = int(u["halted_before_level"])
    unit = Unit(u["unit_id"], u["key"], draft, levels_done=start, notes=list(u["notes"]))
    unit.notes.append(f"re-run #{attempt} from level {start} with corrections: " +
                      ", ".join(f"{f['table']}.{f['field']}={f['value']!r}" for f in fixes))
    rng, fake = _rngs(cfg, seed, unit.unit_id, attempt)
    unit = _advance(unit, start, cfg, plan, registry, xlsource, rng, fake)
    return {"unit_id": unit.unit_id, "key": unit.key, "status": unit.status,
            "halted_before_level": unit.halted_before_level, "levels_done": unit.levels_done,
            "violations": unit.violations, "notes": unit.notes, "draft": unit.draft, "attempts": attempt}


def rerun_in_file(run_path: Path | str, unit_id: int, fixes: list[dict[str, Any]], cfg: Config | None = None) -> dict[str, Any]:
    """Re-run one unit of a saved run file and write the result back into that file."""
    cfg = cfg or load_config()
    path = Path(run_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    idx = next(i for i, u in enumerate(data["units"]) if u["unit_id"] == unit_id)
    plan, registry = build_plan(cfg), load_rules()
    new = rerun_unit(data["units"][idx], fixes, cfg, plan, registry, load_xlsource(cfg, random.Random()))
    data["units"][idx] = new
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return new


# --------------------------------------------------------------------------- #
# Run all units in parallel
# --------------------------------------------------------------------------- #
def run(cfg: Config) -> Path:
    plan = build_plan(cfg)
    registry = load_rules()
    warnings = []
    if registry.version != plan.version:
        warnings.append(f"registry_dump.json (version {plan.version}) is stale vs PolRef.json "
                        f"(version {registry.version}); rerun DAGRegistry/load_rules.py")
    rng = random.Random(cfg.seed)
    xlsource = load_xlsource(cfg, rng)
    used: set[str] = set()
    keys = [new_key(rng, cfg, used) for _ in range(cfg.units)]

    with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as pool:
        futures = [pool.submit(run_unit, i, k, cfg, plan, registry, xlsource, cfg.seed) for i, k in enumerate(keys)]
        units = [f.result() for f in futures]

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    result = {
        "run_id": run_id, "registry_version": registry.version, "warnings": warnings,
        "levels": [[f"{t}.{f}" for t, f in lv] for lv in plan.levels],
        "xlsource_rows": len(xlsource),
        "units": [{"unit_id": u.unit_id, "key": u.key, "status": u.status,
                   "halted_before_level": u.halted_before_level, "levels_done": u.levels_done,
                   "violations": u.violations, "notes": u.notes, "draft": u.draft} for u in units],
    }
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.output_dir / f"run_{run_id}.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", type=int)
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()
    cfg = load_config(units=args.units, seed=args.seed)
    out = run(cfg)
    data = json.loads(out.read_text(encoding="utf-8"))
    for w in data["warnings"]:
        print("WARNING:", w)
    for u in data["units"]:
        extra = ""
        if u["status"] == "needs_review":
            extra = " | " + "; ".join(f"{v['table']}.{v['field']}={v['value']!r}" for v in u["violations"][:3])
        print(f"unit {u['unit_id']:>2} {u['key']} {u['status']:<12} levels_done={u['levels_done']}{extra}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
