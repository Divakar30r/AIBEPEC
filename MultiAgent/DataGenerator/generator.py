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

from count_rules import check_counts
from schema import Branch, Node, Plan, build_plan
from settings import Config, load_config
import formats
import weights as fb_weights
from source import load_db_formats, load_xlsource

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "DAGRegistry"))
from load_rules import _shift, _to_date, load_rules, parse_range_c, same  # noqa: E402  (authoritative validator)

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
    return [b for b in branches if all(same(ctx.get(t, {}).get(f), v) for (t, f), v in b.guards)]


def value_from_branch(b: Branch, ctx: dict[str, dict[str, Any]], table: str, rng: random.Random) -> Any:
    if b.constraint == "ListStr":
        return rng.choice(b.allowed)
    if b.constraint == "RangeInt":
        return rng.randint(*b.allowed)
    if b.constraint == "Range_YYYYMM":
        lo, hi = b.allowed
        months = [y * 100 + m for y in range(lo // 100, hi // 100 + 1) for m in range(1, 13) if lo <= y * 100 + m <= hi]
        return rng.choice(months)
    if b.constraint == "Range_YYYYMMDD":
        lo, hi = (_to_date(x) for x in b.allowed)
        d = lo + timedelta(days=rng.randint(0, (hi - lo).days))
        return int(d.strftime("%Y%m%d"))
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
def key_fields(cfg: Config) -> set[str]:
    return {f"{cfg.parent}.{cfg.key_field}"} | {f"{t}.{c.get('key_field', cfg.key_field)}" for t, c in cfg.children.items()}


def check_all(registry, cfg: Config, plan: Plan, draft: Draft, levels_done: int) -> list[dict[str, Any]]:
    """Field rules (registry) + count rules (count_dump), each only once its inputs were attempted."""
    attempted = plan.attempted(levels_done, key_fields(cfg))
    return validate(registry, cfg, draft, plan, attempted) + check_counts(plan.count_rules, draft, attempted)


def validate(registry, cfg: Config, draft: Draft, plan: Plan | None = None,
             attempted: set[str] | None = None) -> list[dict[str, Any]]:
    parent = cfg.parent
    out: list[dict[str, Any]] = []

    def ready(t: str, f: str) -> bool:
        """Enforce a field rule only when the field and everything it depends on (dependency_graph) were attempted."""
        if attempted is None or plan is None:
            return True
        return f"{t}.{f}" in attempted and all(f"{a}.{b}" in attempted for a, b in (plan.deps or {}).get((t, f), ()))

    def add(v, record: int | None) -> None:
        if ready(v.table, v.field):
            out.append({"kind": "field", "table": v.table, "field": v.field, "record": record,
                        "value": v.value, "reason": v.reason})

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
             rng: random.Random, fake: Faker, weights: "fb_weights.Weights | None" = None) -> Unit:
    """Validate-then-fill each level from start_lvl; halts the unit on the first violation."""
    parent, draft = cfg.parent, unit.draft
    dbf = load_db_formats(cfg)  # target -> DB-type format; every value is stored in it
    source_row: dict[tuple[str, int], dict[str, Any]] = {}  # one XLSource row per record keeps name/age coherent
    draws: dict[tuple, float] = {}  # Only/Max Possibility: one draw per parent value for the whole unit

    def records(table: str) -> list[tuple[int | None, dict[str, Any]]]:
        return [(None, draft[table])] if table == parent else list(enumerate(draft[table]))

    try:
        for lvl in range(start_lvl, len(plan.levels)):
            nodes = plan.levels[lvl]
            if lvl > 0:
                unit.violations = check_all(registry, cfg, plan, draft, lvl)
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
                        if weights:  # user-weighted LLM value pairs from earlier runs (no LLM call)
                            rec[fld], note = weights.remap(table, fld, rec[fld], rng)
                            if note:
                                unit.notes.append(note)
                    elif (table, fld) in plan.rules:                                # C) rule
                        options = applicable(plan.rules[(table, fld)], ctx)
                        if not options:
                            unit.notes.append(f"{target}: no rule branch applies to current values - left blank")
                            continue
                        rec[fld] = formats.convert(value_from_branch(rng.choice(options), ctx, table, rng),
                                                   dbf.get(target))  # rules give bounds; stored in the DB type
                    else:                                                           # D) Faker
                        rec[fld] = formats.convert(faker_value(cfg.faker.get(target, cfg.faker_default), fake, rng),
                                                   dbf.get(target))
            if weights:  # user-weighted LLM count pairs: steer how many related records carry each value
                for table, fld in nodes:
                    if table == parent:
                        continue

                    def opts(rec, table=table, fld=fld):
                        bs = applicable(plan.rules.get((table, fld), ()), {parent: draft[parent], table: rec})
                        return [x for b in bs if b.constraint == "ListStr" for x in b.allowed]
                    unit.notes += weights.adjust_counts(draft, parent, table, fld, opts, rng, draws)
            unit.levels_done = lvl + 1
        unit.violations = check_all(registry, cfg, plan, draft, len(plan.levels))  # final check after the last level
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
             seed: int | None, weights: "fb_weights.Weights | None" = None) -> Unit:
    rng, fake = _rngs(cfg, seed, unit_id)
    # A) primary key on every record of the unit; record counts per child table.
    draft: Draft = {cfg.parent: {cfg.key_field: key}}
    for child, c in cfg.children.items():
        n = rng.randint(c["min_per_key"], c["max_per_key"])
        draft[child] = [{c.get("key_field", cfg.key_field): key} for _ in range(n)]
    return _advance(Unit(unit_id, key, draft), 0, cfg, plan, registry, xlsource, rng, fake, weights)


def rerun_unit(u: dict[str, Any], fixes: list[dict[str, Any]], cfg: Config, plan: Plan, registry,
               xlsource: list[dict[str, Any]], seed: int | None = None,
               deletions: dict[str, list[int]] | None = None) -> dict[str, Any]:
    """Apply manual corrections to a halted unit and resume from the level it stopped before.

    u is a unit dict as stored in a run file. fixes: [{"table", "record", "field", "value"}].
    Levels already filled are kept; only the remaining levels are (re)generated.
    """
    if u["status"] != "needs_review" or u["halted_before_level"] is None:
        raise ValueError(f"unit {u['unit_id']} is not halted for review")
    draft = json.loads(json.dumps(u["draft"]))  # deep copy
    dbf = load_db_formats(cfg)  # keyed-in and LLM-converted values are stored in the target's db_format
    for f in fixes:  # values first: record indices refer to the draft as shown in the UI
        rec = draft[f["table"]] if f["record"] is None else draft[f["table"]][f["record"]]
        rec[f["field"]] = formats.convert(f["value"], dbf.get(f"{f['table']}.{f['field']}"))
    removed = []
    for table, idxs in (deletions or {}).items():
        if table == cfg.parent:
            raise ValueError("deleting the parent record deletes the unit - use delete_unit_in_file")
        for i in sorted(set(idxs), reverse=True):
            del draft[table][i]
        removed.append(f"{table} records {sorted(set(idxs))}")
        lo = cfg.children.get(table, {}).get("min_per_key")
        if lo is not None and len(draft[table]) < lo:
            removed.append(f"{table} now has {len(draft[table])} record(s), below configured min {lo}")
    attempt = int(u.get("attempts", 0)) + 1
    start = int(u["halted_before_level"])
    unit = Unit(u["unit_id"], u["key"], draft, levels_done=start, notes=list(u["notes"]))
    unit.notes.append(f"re-run #{attempt} from level {start}; corrections: " +
                      (", ".join(f"{f['table']}.{f['field']}={f['value']!r}" for f in fixes) or "none") +
                      ("; deleted " + "; ".join(removed) if removed else ""))
    rng, fake = _rngs(cfg, seed, unit.unit_id, attempt)
    unit = _advance(unit, start, cfg, plan, registry, xlsource, rng, fake)
    return {"unit_id": unit.unit_id, "key": unit.key, "status": unit.status,
            "halted_before_level": unit.halted_before_level, "levels_done": unit.levels_done,
            "violations": unit.violations, "notes": unit.notes, "draft": unit.draft, "attempts": attempt}


def delete_unit_in_file(run_path: Path | str, unit_id: int) -> None:
    """Delete the parent record, i.e. the whole unit, from a saved run file."""
    path = Path(run_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    gone = [u for u in data["units"] if u["unit_id"] == unit_id]
    data["units"] = [u for u in data["units"] if u["unit_id"] != unit_id]
    data.setdefault("deleted_units", []).append(unit_id)
    # keep the removed unit as it was (draft + violations): its count errors become "problem" feedback pairs
    data.setdefault("removed_units", []).extend(gone)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    collect_if_done(path)


def _record_change(changes: list[dict[str, Any]], new: dict[str, Any]) -> None:
    """Append an authored change, folding it into the same author's previous change of the same cell:
    an intermediate value the author overwrote themselves is not tracked (only original -> latest is kept;
    changing it back to the original drops the entry). Chained on the value, so stale record indices
    after deletions don't merge unrelated cells."""
    for i in range(len(changes) - 1, -1, -1):
        prev = changes[i]
        if (prev["table"], prev.get("record"), prev["field"]) == (new["table"], new.get("record"), new["field"]) \
                and str(prev.get("to")) == str(new.get("from")):
            merged = {**new, "from": prev.get("from")}
            del changes[i]
            if str(merged["from"]) != str(merged["to"]):
                changes.append(merged)
            return
    changes.append(new)


def _rerun_once(path: Path, unit_id: int, fixes: list[dict[str, Any]], cfg: Config,
                deletions: dict[str, list[int]] | None = None, by_llm: bool = False) -> dict[str, Any]:
    """Apply fixes/deletions, re-run one unit from its halted level, write it back. No LLM call."""
    data = json.loads(path.read_text(encoding="utf-8"))
    idx = next(i for i, u in enumerate(data["units"]) if u["unit_id"] == unit_id)
    old = data["units"][idx]
    applied = list(old.get("llm_applied", []))
    by_user = list(old.get("user_applied", []))
    # remember who changed what (LLM: shown + editable in the UI; both feed LLMfeedback.json once the run is done)
    dbf = load_db_formats(cfg)
    for f in fixes:
        rec = old["draft"][f["table"]] if f["record"] is None else old["draft"][f["table"]][f["record"]]
        stored = formats.convert(f["value"], dbf.get(f"{f['table']}.{f['field']}"))  # as rerun_unit stores it
        _record_change(applied if by_llm else by_user, {
            **{k: f[k] for k in ("table", "record", "field")}, "from": rec.get(f["field"]), "to": stored,
            "level": old["halted_before_level"], "attempt": int(old.get("attempts", 0)) + 1})
    # snapshot of this halt's count errors (with the parent row as it was) - the "problem" side of count pairs
    halts = list(old.get("halts", []))
    count_v = [v for v in old.get("violations", []) if v.get("kind") == "count"]
    if count_v:
        halts.append({"attempt": int(old.get("attempts", 0)), "level": old["halted_before_level"],
                      "parent": dict(old["draft"][cfg.parent]), "count_violations": count_v})
    plan, registry = build_plan(cfg), load_rules()
    new = rerun_unit(old, fixes, cfg, plan, registry, load_xlsource(cfg, random.Random()), deletions=deletions)
    for k, v in (("llm_applied", applied), ("user_applied", by_user), ("halts", halts)):
        if v:
            new[k] = v
    data["units"][idx] = new
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return new


def _unit(path: Path, unit_id: int) -> dict[str, Any]:
    return next(u for u in json.loads(path.read_text(encoding="utf-8"))["units"] if u["unit_id"] == unit_id)


def _llm_cycle(path: Path, unit_id: int, cfg: Config, reviewed: bool = False) -> dict[str, Any]:
    """Level by level: LLM review -> auto-apply its A) conversions -> resume, until the unit completes,
    the LLM has no (new) conversion, or one pass per level was used. The final halt is always reviewed,
    so its B/C proposals are available in the UI."""
    levels = len(json.loads(path.read_text(encoding="utf-8")).get("levels", [])) or 1
    u = _unit(path, unit_id)
    for _ in range(levels + 1):
        if u["status"] != "needs_review":
            return u
        if not reviewed:
            llm_review(path, [unit_id], trigger="rerun")
        reviewed = False
        rec = lambda f: u["draft"][f["table"]] if f["record"] is None else u["draft"][f["table"]][f["record"]]  # noqa: E731
        try:
            fixes = [f for f in llm_conversions(path, u) if rec(f).get(f["field"]) != f["value"]]
        except (KeyError, IndexError, TypeError):
            fixes = []
        if not fixes:
            return u  # nothing new to convert: leave for manual review
        u = _rerun_once(path, unit_id, fixes, cfg, by_llm=True)
    if u["status"] == "needs_review":
        llm_review(path, [unit_id], trigger="rerun")
    return u


def rerun_in_file(run_path: Path | str, unit_id: int, fixes: list[dict[str, Any]], cfg: Config | None = None,
                  deletions: dict[str, list[int]] | None = None, llm: bool = True) -> dict[str, Any]:
    """Apply manual corrections and/or delete related records, re-run one unit, write it back into the file.
    If it halts again (and llm_review is on), the LLM A) cycle runs level by level from there."""
    cfg = cfg or load_config()
    path = Path(run_path)
    new = _rerun_once(path, unit_id, fixes, cfg, deletions)
    if llm and cfg.llm_review and new["status"] == "needs_review":
        new = _llm_cycle(path, unit_id, cfg)
    collect_if_done(path)
    return new


def swap_child_sets(run_path: Path | str, assignment: dict[int, int], cfg: Config | None = None) -> dict[int, str]:
    """Re-key whole related-table sets between HALTED units (no LLM call): {unit_id: donor_unit_id} gives
    unit_id all child records of donor_unit_id, re-keyed to unit_id's key. Completed units are never touched.
    Each changed unit resumes from its halted level. Provenance is kept in repair_applied.
    Returns {unit_id: new status}."""
    cfg = cfg or load_config()
    path = Path(run_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {u["unit_id"]: u for u in data["units"]}
    for uid, donor in assignment.items():
        for x in (uid, donor):
            if x not in by_id or by_id[x]["status"] != "needs_review":
                raise ValueError(f"unit {x} is not a halted unit - only halted units can swap related sets")
    originals = {x: json.loads(json.dumps(by_id[x]["draft"])) for x in set(assignment) | set(assignment.values())}
    plan, registry = build_plan(cfg), load_rules()
    xls = load_xlsource(cfg, random.Random())
    out: dict[int, str] = {}
    for uid, donor in assignment.items():
        if uid == donor:
            continue
        old = by_id[uid]
        draft = json.loads(json.dumps(old["draft"]))
        moved = {}
        for child, c in cfg.children.items():
            kf = c.get("key_field", cfg.key_field)
            draft[child] = [{**r, kf: old["key"]} for r in originals[donor].get(child, [])]
            moved[child] = len(draft[child])
        new = rerun_unit({**old, "draft": draft}, [], cfg, plan, registry, xls)
        for k, v in old.items():  # keep provenance (llm_applied, user_applied, halts, ...)
            new.setdefault(k, v)
        new["repair_applied"] = list(old.get("repair_applied", [])) + [{
            "from_unit": donor, "from_key": by_id[donor]["key"], "to_unit": uid, "records": moved,
            "level": old["halted_before_level"], "attempt": new["attempts"]}]
        new["notes"].append(f"repair (supervisor): related records taken from unit {donor} ({by_id[donor]['key']}), "
                            f"re-keyed to {old['key']} - no LLM call")
        data["units"] = [new if u["unit_id"] == uid else u for u in data["units"]]
        out[uid] = new["status"]
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    collect_if_done(path)
    return out


def llm_conversions(run_path: Path | str, unit: dict[str, Any]) -> list[dict[str, Any]]:
    """The LLM's A) conversions for this unit's current attempt, as re-run fixes (stale reviews ignored)."""
    path = Path(run_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    rv_path = path.parent / f"llm_review_{data['run_id']}.json"
    if not rv_path.exists():
        return []
    rv = next((r for r in json.loads(rv_path.read_text(encoding="utf-8"))["units"]
               if r["unit_id"] == unit["unit_id"]), None)
    if not rv or rv.get("attempts", 0) != unit.get("attempts", 0):
        return []
    return [{"table": c["table"], "record": c.get("record"), "field": c["field"], "value": c["to"]}
            for c in rv.get("conversions") or [] if c.get("to") not in (None, "")]


def apply_llm_conversions(run_path: Path | str, unit_ids: list[int] | None = None,
                          cfg: Config | None = None) -> dict[int, str]:
    """For each halted unit with a current review: auto-apply A) conversions and resume, level by level
    (see _llm_cycle). B) count decisions and C) suggestions are never applied. Returns {unit_id: status}."""
    cfg = cfg or load_config()
    path = Path(run_path)
    ids = [u["unit_id"] for u in json.loads(path.read_text(encoding="utf-8"))["units"]
           if u["status"] == "needs_review" and (unit_ids is None or u["unit_id"] in unit_ids)]
    out = {i: _llm_cycle(path, i, cfg, reviewed=True)["status"] for i in ids}
    collect_if_done(path)
    return out


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
    if plan.count_rules is None:
        warnings.append("count_dump.json not found - count rules are not checked")
    else:
        import hashlib
        src = cfg.count_dump.parent.parent / plan.count_rules.get("source", "PolRefCount.json")
        if src.exists() and hashlib.sha256(src.read_bytes()).hexdigest()[:12] != plan.count_version:
            warnings.append(f"count_dump.json is stale vs {src.name}; rerun DAGRegistry/load_count_rules.py")
    rng = random.Random(cfg.seed)
    xlsource = load_xlsource(cfg, rng)
    used: set[str] = set()
    keys = [new_key(rng, cfg, used) for _ in range(cfg.units)]
    try:  # weights the user set on earlier runs' LLM output; only NEW runs use them
        weights = fb_weights.load_weights()
    except Exception as e:
        weights = None
        warnings.append(f"LLM feedback weights not loaded: {e}")

    with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as pool:
        futures = [pool.submit(run_unit, i, k, cfg, plan, registry, xlsource, cfg.seed, weights) for i, k in enumerate(keys)]
        units = [f.result() for f in futures]

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    result = {
        "run_id": run_id, "registry_version": registry.version, "count_rules_version": plan.count_version,
        "warnings": warnings,
        "levels": [[f"{t}.{f}" for t, f in lv] for lv in plan.levels],
        "xlsource_rows": len(xlsource),
        "per_key": {t: [c["min_per_key"], c["max_per_key"]] for t, c in cfg.children.items()},
        "units": [{"unit_id": u.unit_id, "key": u.key, "status": u.status,
                   "halted_before_level": u.halted_before_level, "levels_done": u.levels_done,
                   "violations": u.violations, "notes": u.notes, "draft": u.draft} for u in units],
    }
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.output_dir / f"run_{run_id}.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    if cfg.llm_review and any(u.status == "needs_review" for u in units):
        llm_review(out)
        # Automatically, level by level: apply the LLM's A) conversions to each halted draft and resume it, so
        # every next level's dependency check runs on converted values. B/C are never applied.
        try:
            apply_llm_conversions(out, cfg=cfg)
        except Exception as e:
            print(f"Auto-apply of LLM conversions failed: {e}", file=sys.stderr)
            _add_warning(out, f"Auto-apply of LLM conversions failed: {e}")
    collect_if_done(out)
    return out


def run_done(data: dict[str, Any]) -> bool:
    """Every remaining unit went through (completed); deleted units no longer count."""
    return bool(data.get("units")) and all(u["status"] == "completed" for u in data["units"])


def collect_if_done(run_path: Path | str) -> dict[str, int] | None:
    """Once ALL units of the run went through - i.e. after the user's corrections in the UI - merge the run's
    final outcome (LLM changes + user corrections) into LLMfeedback.json. Exactly once per run."""
    path = Path(run_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("feedback_collected") or not run_done(data):
        return None
    res = collect_feedback(path)
    if res is not None:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["feedback_collected"] = datetime.now().isoformat(timespec="seconds")
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return res


def collect_feedback(run_path: Path | str) -> dict[str, int] | None:
    """Merge this run's A/B LLM output into ../LLMEffects/LLMfeedback.json (unique pairs, +-1 weights kept)."""
    try:
        return fb_weights.merge_run(run_path)
    except Exception as e:
        print(f"Collecting LLM feedback failed: {e}", file=sys.stderr)
        return None


def llm_review(run_path: Path, unit_ids: list[int] | None = None, trigger: str = "run") -> str | None:
    """Hand the run to ../LLMEffects/review.py (separate process: its modules share names with ours).
    Writes llm_review_<run_id>.json next to the run; a failure never breaks the run.
    Returns an error message, or None on success (the message is also recorded in the run's warnings)."""
    import subprocess
    script = Path(__file__).resolve().parent.parent / "LLMEffects" / "review.py"
    try:
        cmd = [sys.executable, str(script), str(run_path), f"--trigger={trigger}"]
        if unit_ids:
            cmd.append("--units=" + ",".join(map(str, unit_ids)))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        err = f"LLM review failed: {r.stderr.strip()[-500:]}" if r.returncode else None
    except Exception as e:
        err = f"LLM review failed: {e}"
    if err:
        print(err, file=sys.stderr)
        _add_warning(run_path, err)
    return err


def _add_warning(run_path: Path, msg: str) -> None:
    """Record a problem in the run file so the UI shows it (not only the server log)."""
    try:
        data = json.loads(Path(run_path).read_text(encoding="utf-8"))
        data.setdefault("warnings", []).append(msg)
        Path(run_path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as e:  # never break the run over a warning
        print(f"Could not record warning: {e}", file=sys.stderr)


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
