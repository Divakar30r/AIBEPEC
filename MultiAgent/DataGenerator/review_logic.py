"""Review logic shared by the Streamlit app (app.py) and the React UI's API (../ReviewUI/backend) - no UI code.

    rules_dump(cfg)                    registry_dump.json rules ({"Table.Field": {...}})
    allowed_for(rules, t, f, ctx)      the rule options for one row context (kind, spec, scoped)
    editor_spec(...)                   how one cell is edited: select / int / date / text (+ options, bounds, format)
    field_options(...)                 editors for a whole record from the values of the fields each one depends on
    load_llm_review(run_path)          llm_review_<run_id>.json -> {unit_id: review}
    llm_for / llm_values               the LLM review of a unit's CURRENT attempt, and its proposed values
    cells(v) / cell_value(u, c)        cells a violation lets the reviewer change / a cell's current draft value
    edit_plan(cfg, u, review)          editable cells (with prefills) + records proposed for deletion
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import formats
import generator
from settings import Config

MISSING = object()
DATE_KINDS = ("Range_YYYYMMDD", "Range_YYYYMM")
INT_KINDS = ("RangeInt",) + DATE_KINDS


def rules_dump(cfg: Config) -> dict[str, Any]:
    try:
        return json.loads(Path(cfg.registry_dump).read_text(encoding="utf-8"))["rules"]
    except (OSError, KeyError, json.JSONDecodeError):
        return {}


def _ref(ref: str) -> tuple[str, str]:
    table, _, fld = ref.partition(".")
    return table, fld


def allowed_for(rules: dict[str, Any], table: str, fld: str, ctx: dict) -> tuple[str, object, bool] | None:
    """(kind, spec, scoped) from registry_dump.json. Only branches whose guards match ctx are used;
    if none match, all branches are offered (scoped=False)."""
    rule = rules.get(f"{table}.{fld}")
    if not rule or not rule["branches"]:
        return None
    ok = [b for b in rule["branches"]
          if all(generator.same(ctx.get(_ref(g)[0], {}).get(_ref(g)[1]), v) for g, v in b["guards"].items())]
    use = ok or rule["branches"]
    kind = use[0]["constraint"]
    use = [b for b in use if b["constraint"] == kind]
    if kind == "ListStr":
        return kind, list(dict.fromkeys(x for b in use for x in b["allowed"])), bool(ok)
    if kind in INT_KINDS:
        return kind, (min(b["allowed"][0] for b in use), max(b["allowed"][1] for b in use)), bool(ok)
    return kind, use[0]["allowed"], bool(ok)


def row_of(u: dict[str, Any], table: str, rec: int | None) -> dict[str, Any]:
    return u["draft"][table] if rec is None else u["draft"][table][rec]


def editor_spec(cfg: Config, rules: dict[str, Any], dbf: dict[str, str], u: dict[str, Any],
                table: str, rec: int | None, fld: str) -> dict[str, Any]:
    """How a reviewer edits one cell (mirrors app.correction_widget):
    {"editor": "select"|"int"|"number"|"date"|"text", "options"?, "min"?, "max"?, "format"? (date token the value
    is stored in), "rule": constraint kind or None, "scoped": False when no rule branch matches the row, "help"}."""
    row = row_of(u, table, rec)
    ctx = {cfg.parent: u["draft"][cfg.parent], table: row}
    return _spec(allowed_for(rules, table, fld, ctx), formats.norm(dbf.get(f"{table}.{fld}")))


def _plain(db_fmt: str | None, help_: str) -> dict[str, Any]:
    """No rule (or not usable yet): an input that fits the DB column type."""
    if formats.is_date_format(db_fmt):
        return {"editor": "date", "format": db_fmt, "rule": None, "scoped": True, "help": f"{help_}; stored as {db_fmt}"}
    if db_fmt in formats.INTEGER:
        return {"editor": "int", "rule": None, "scoped": True, "help": help_}
    if db_fmt in formats.DECIMAL:
        return {"editor": "number", "rule": None, "scoped": True, "help": help_}
    return {"editor": "text", "rule": None, "scoped": True, "help": help_}


def field_options(cfg: Config, rules: dict[str, Any], dbf: dict[str, str], table: str, fields: list[str],
                  values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The editor of each field of one `table` record, from the values given for the fields it depends on.
    values: {"Table.Field": value} - the record being edited plus its parent record, including edits not
    saved yet (so a field picked a moment ago already narrows the next dropdown).
    A list rule gives a dropdown ONLY when every field it depends on (registry depends_on) has a value; if one
    is missing there is no dropdown - fill the listed fields first. Each spec also carries depends_on/missing."""
    ctx: dict[str, dict[str, Any]] = {}
    for ref, v in values.items():
        t, f = _ref(ref)
        ctx.setdefault(t, {})[f] = v
    out: dict[str, dict[str, Any]] = {}
    for fld in fields:
        rule = rules.get(f"{table}.{fld}")
        deps = list((rule or {}).get("depends_on") or [])
        missing = [d for d in deps if values.get(d) in (None, "")]
        db_fmt = formats.norm(dbf.get(f"{table}.{fld}"))
        if rule is None:
            spec = _plain(db_fmt, "No rule - free value")
        elif missing:
            spec = _plain(db_fmt, "Fill first: " + ", ".join(missing) + " (no dropdown until then)")
        else:
            spec = _spec(allowed_for(rules, table, fld, ctx), db_fmt)
            if not spec.get("scoped", True):
                spec["help"] = ("No rule branch matches " + ", ".join(f"{d}={values.get(d)!r}" for d in deps)
                                + " - showing all options")
        out[fld] = {**spec, "depends_on": deps, "missing": missing}
    return out


def _spec(found: tuple[str, object, bool] | None, db_fmt: str | None) -> dict[str, Any]:
    if found is None:
        return _plain(db_fmt, "No rule")
    kind, spec, scoped = found
    base = {"rule": kind, "scoped": scoped}
    if kind in DATE_KINDS:  # rule = calendar bounds; the value is stored in the DB type
        pat = "YYYYMMDD" if kind == "Range_YYYYMMDD" else "YYYYMM"
        lo, hi = (formats.parse_date(str(x), pat) for x in spec)
        fmt = db_fmt if formats.is_date_format(db_fmt) else "YYYY-MM-DD"
        return {**base, "editor": "date", "format": fmt, "min": lo.date().isoformat() if lo else None,
                "max": hi.date().isoformat() if hi else None, "help": f"Allowed {spec[0]} .. {spec[1]}; stored as {fmt}"}
    if kind == "Range_C" and formats.is_date_format(db_fmt):
        return {**base, "editor": "date", "format": db_fmt, "help": f"Rule: {spec}; stored as {db_fmt}"}
    if kind == "ListStr":
        return {**base, "editor": "select", "options": list(spec),
                "help": None if scoped else "No rule branch matches this row's values - showing all options"}
    if kind in INT_KINDS:
        return {**base, "editor": "int", "min": spec[0], "max": spec[1], "help": f"Allowed {spec[0]} .. {spec[1]}"}
    return {**base, "editor": "text", "help": f"Rule: {spec}"}


def to_stored(spec: dict[str, Any], value: Any) -> Any:
    """A value from the UI in the form it is stored: ISO dates -> the field's date format, ints -> int."""
    if value in (None, ""):
        return value
    if spec.get("editor") == "date":
        d = formats.parse_date(value, "YYYY-MM-DD")
        return d.strftime(formats.DATE_FORMATS[spec["format"]]) if d else value
    if spec.get("editor") == "int" and str(value).strip().lstrip("-").isdigit():
        return int(str(value).strip())
    return value


def load_llm_review(run_path: Path | str, run_id: str) -> dict[int, dict[str, Any]]:
    """{unit_id: review} from llm_review_<run_id>.json next to the run file ({} if missing/unreadable)."""
    p = Path(run_path).parent / f"llm_review_{run_id}.json"
    try:
        return {u["unit_id"]: u for u in json.loads(p.read_text(encoding="utf-8"))["units"]} if p.exists() else {}
    except (OSError, KeyError, json.JSONDecodeError):
        return {}


def llm_for(reviews: dict[int, dict[str, Any]], u: dict[str, Any]) -> dict[str, Any] | None:
    """The LLM review of this unit's current attempt (older attempts are stale)."""
    r = reviews.get(u["unit_id"])
    return r if r and r.get("attempts", 0) == u.get("attempts", 0) else None


def llm_values(review: dict[str, Any] | None) -> dict[tuple, Any]:
    """(table, record, field) -> value proposed by the LLM (conversions + count decisions)."""
    r = review or {}
    return {(c.get("table"), c.get("record"), c.get("field")): c.get("to")
            for c in (r.get("conversions") or []) + (r.get("count_decisions") or []) if c.get("field") != "__delete__"}


def cells(v: dict[str, Any]) -> list[tuple[str, int | None, str]]:
    """(table, record, field) a reviewer can change for one violation; count errors expand to their records."""
    if v.get("kind") == "count":
        return [(v["table"], r, v["field"]) for r in v.get("records", [])]
    return [(v["table"], v["record"], v["field"])]


def cell_value(u: dict[str, Any], c: dict[str, Any]):
    """Current draft value of a (table, record, field) reference, or MISSING if it does not exist."""
    try:
        t, r = u["draft"][c.get("table")], c.get("record")
        row = t if r is None else t[int(r)]
        return row[c.get("field")] if c.get("field") in row else MISSING
    except (KeyError, IndexError, TypeError, ValueError):
        return MISSING


def suggested_deletions(u: dict[str, Any], review: dict[str, Any] | None) -> dict[str, list[int]]:
    """Records to pre-select for deletion: over a count rule's maximum, or LLM delete proposals."""
    out: dict[str, list[int]] = {}
    for v in u["violations"]:
        if v.get("kind") == "count" and v["count"] > v["allowed_count"][1]:
            out.setdefault(v["table"], []).extend(v["records"])
    for c in (review or {}).get("count_decisions") or []:
        if c.get("field") == "__delete__" and isinstance(c.get("record"), int):
            out.setdefault(c.get("table"), []).append(c["record"])
    return {t: sorted(set(rs)) for t, rs in out.items()}


def edit_plan(cfg: Config, rules: dict[str, Any], dbf: dict[str, str], u: dict[str, Any],
              review: dict[str, Any] | None) -> dict[str, Any]:
    """Editable cells of a halted unit: its violation cells + cells the LLM changed or proposes (A applied,
    B/C proposals), each with its editor spec and prefill; plus the records proposed for deletion."""
    prefill: dict[tuple, Any] = {}
    for c in u.get("llm_applied") or []:
        prefill.setdefault((c["table"], c["record"], c["field"]), cell_value(u, c))
    for c in (review or {}).get("suggestions") or []:
        prefill[(c.get("table"), c.get("record"), c.get("field"))] = c.get("suggested")
    prefill.update(llm_values(review))
    bad = {c for v in u["violations"] for c in cells(v)}
    targets = list(dict.fromkeys(list(bad) + list(prefill)))
    out = []
    for t, r, f in targets:
        cur = cell_value(u, {"table": t, "record": r, "field": f})
        if cur is MISSING:
            continue
        pre = prefill.get((t, r, f))
        out.append({"table": t, "record": r, "field": f, "current": cur, "violation": (t, r, f) in bad,
                    "prefill": None if pre is MISSING else pre,
                    "spec": editor_spec(cfg, rules, dbf, u, t, r, f)})
    return {"cells": out, "delete": suggested_deletions(u, review)}
