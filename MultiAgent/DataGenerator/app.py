"""Review UI for generated units.   streamlit run app.py"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import dbschema
import importlib

import count_rules
import generator
import schema

# Streamlit reruns app.py on save but keeps imported modules cached; reload so code changes apply.
for _m in (count_rules, schema, generator):
    importlib.reload(_m)
from settings import load_config

st.set_page_config(page_title="Draft review", layout="wide")
try:
    cfg = load_config()
except (dbschema.SchemaError, ValueError) as e:
    st.error(f"Cannot derive the table relations from the database foreign keys: {e}")
    st.stop()

st.title("Generated drafts - review")

with st.sidebar:
    st.header("Run")
    units = st.number_input("Units", 1, 500, cfg.units)
    seed = st.number_input("Seed (0 = random)", 0, 10**6, 0)

    st.subheader("Related tables (records per key)")
    st.caption(f"Parent: {cfg.parent} (key {cfg.key_field}) - database {cfg.db_name}")
    # Nothing is pre-filled: every related table needs an explicit min and max before Execute is enabled.
    per_key: dict[str, tuple[int, int]] = {}
    problems: list[str] = []
    for child, c in cfg.children.items():
        st.markdown(f"**{child}**")
        st.caption(f"{c['key_field']} -> {cfg.parent}.{cfg.key_field} via {c['fk']} "
                    f"(config default {c['min_per_key']}..{c['max_per_key']})")
        lo_col, hi_col = st.columns(2)
        lo = lo_col.number_input("min", 1, 1000, value=None, step=1, key=f"min_{child}", placeholder="required")
        hi = hi_col.number_input("max", 1, 1000, value=None, step=1, key=f"max_{child}", placeholder="required")
        if lo is None or hi is None:
            problems.append(f"{child}: enter min and max")
        elif lo > hi:
            problems.append(f"{child}: min must not exceed max")
        else:
            per_key[child] = (int(lo), int(hi))
    if not cfg.children:
        problems.append("No related tables found from the database foreign keys")
    for p in problems:
        st.caption(f":red[{p}]")
    if st.button("Reload schema from database"):
        dbschema.clear_cache()
        st.rerun()

    # Runs only on click; disabled until every related table is configured.
    if st.button("Execute", type="primary", disabled=bool(problems),
                 help="Fill in min and max for every related table first" if problems else None):
        with st.spinner("Generating..."):
            generator.run(load_config(units=int(units), seed=int(seed) or None, per_key=per_key))
        st.rerun()
    files = sorted(Path(cfg.output_dir).glob("run_*.json"), reverse=True)
    choice = st.selectbox("Run file", files, format_func=lambda p: p.stem) if files else None

if choice is None:
    st.info("No runs yet. Fill in the related tables and press 'Execute' in the sidebar, or run `python generator.py`.")
    st.stop()

run = json.loads(Path(choice).read_text(encoding="utf-8"))
units_ = run["units"]
by_status = lambda s: [u for u in units_ if u["status"] == s]  # noqa: E731

for w in run["warnings"]:
    st.warning(w)

n_count = sum(1 for u in units_ for v in u["violations"] if v.get("kind") == "count")
c1, c2, c3, c4, c5 = st.columns(5)
c5.metric("Count rule errors", n_count)
c1.metric("Units", len(units_))
c2.metric("Completed", len(by_status("completed")))
c3.metric("Needs review", len(by_status("needs_review")))
c4.metric("Error", len(by_status("error")))

with st.expander("Level plan (evaluation order)"):
    for i, lv in enumerate(run["levels"]):
        st.write(f"**Level {i}**: " + ", ".join(lv))

st.subheader("All units")
st.dataframe(pd.DataFrame([{
    "unit": u["unit_id"], "key": u["key"], "status": u["status"], "levels_done": u["levels_done"],
    "halted_before_level": u["halted_before_level"],
    "field errors": sum(1 for v in u["violations"] if v.get("kind", "field") == "field"),
    "count errors": sum(1 for v in u["violations"] if v.get("kind") == "count"),
} for u in units_]), width="stretch", hide_index=True)

st.subheader("Needs manual review")
flagged = by_status("needs_review") + by_status("error")
if not flagged:
    st.success("Nothing to review.")


def show(data) -> pd.DataFrame:
    """Draft records as text: CSV values (str) and generated ones (int) can share a column."""
    return pd.DataFrame(data if isinstance(data, list) else [data]).astype("string")


def cells(v: dict) -> list[tuple[str, int | None, str]]:
    """(table, record, field) a reviewer can change for one violation; count errors expand to their records."""
    if v.get("kind") == "count":
        return [(v["table"], r, v["field"]) for r in v.get("records", [])]
    return [(v["table"], v["record"], v["field"])]


def highlight(table: str, violations: list[dict]):
    bad = {(r or 0, f) for v in violations for t, r, f in cells(v) if t == table}

    def style(df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame("", index=df.index, columns=df.columns)
        for i, f in bad:
            if i in out.index and f in out.columns:
                out.loc[i, f] = "background-color: #f8b4b4; color: #7a0000; font-weight: 600"
        return out
    return style


try:
    RULES = json.loads(Path(cfg.registry_dump).read_text(encoding="utf-8"))["rules"]
except (OSError, KeyError, json.JSONDecodeError):
    RULES = {}
    st.warning(f"Registry dump not readable ({cfg.registry_dump}); correction fields fall back to free text.")


def _ref(ref: str) -> tuple[str, str]:
    table, _, fld = ref.partition(".")
    return table, fld


def allowed_for(table: str, fld: str, ctx: dict) -> tuple[str, object, bool] | None:
    """(kind, spec, scoped) from registry_dump.json. Only branches whose guards match ctx are used;
    if none match, all branches are offered (scoped=False)."""
    rule = RULES.get(f"{table}.{fld}")
    if not rule or not rule["branches"]:
        return None
    ok = [b for b in rule["branches"]
          if all(ctx.get(_ref(g)[0], {}).get(_ref(g)[1]) == v for g, v in b["guards"].items())]
    use = ok or rule["branches"]
    kind = use[0]["constraint"]
    use = [b for b in use if b["constraint"] == kind]
    if kind == "ListStr":
        return kind, list(dict.fromkeys(x for b in use for x in b["allowed"])), bool(ok)
    if kind in ("RangeInt", "Range_YYYYMM", "Range_YYYYMMDD"):
        return kind, (min(b["allowed"][0] for b in use), max(b["allowed"][1] for b in use)), bool(ok)
    return kind, use[0]["allowed"], bool(ok)


def correction_widget(u: dict, table: str, rec: int | None, fld: str):
    row = u["draft"][table] if rec is None else u["draft"][table][rec]
    ctx = {cfg.parent: u["draft"][cfg.parent], table: row}
    key = f"fix_{u['unit_id']}_{u.get('attempts', 0)}_{table}_{rec}_{fld}"
    label = f"{table}.{fld}" + (f" [record {rec}]" if rec is not None else "")
    hint = f"current: {row.get(fld)!r}"
    found = allowed_for(table, fld, ctx)
    if found is None:
        return st.text_input(label, key=key, placeholder=hint, help="No rule in registry_dump.json - free text")
    kind, spec, scoped = found
    if kind == "ListStr":
        help_ = None if scoped else "No rule branch matches the current values of the fields it depends on - showing all options"
        return st.selectbox(label, spec, index=None, key=key, placeholder=hint, help=help_)
    if kind in ("RangeInt", "Range_YYYYMM", "Range_YYYYMMDD"):
        return st.number_input(label, min_value=spec[0], max_value=spec[1], value=None, step=1, key=key,
                               placeholder=hint, help=f"Allowed {spec[0]} .. {spec[1]}" + ({"Range_YYYYMM": " (YYYYMM)", "Range_YYYYMMDD": " (YYYYMMDD, real date)"}.get(kind, "")))
    return st.text_input(label, key=key, placeholder=hint, help=f"Rule: {spec}")


for u in flagged:
    stage = f"halted before level {u['halted_before_level']}" if u["halted_before_level"] is not None else u["status"]
    with st.expander(f"Unit {u['unit_id']} - {u['key']} - {u['status']} ({stage})"):
        if u["violations"]:
            field_v = [v for v in u["violations"] if v.get("kind", "field") == "field"]
            count_v = [v for v in u["violations"] if v.get("kind") == "count"]
            if field_v:
                st.markdown("**Contradicting fields** (registry rules)")
                st.dataframe(pd.DataFrame(field_v).drop(columns=["kind"], errors="ignore").astype("string"),
                             width="stretch", hide_index=True)
            if count_v:
                st.markdown("**Count rule errors** (count_dump.json)")
                st.dataframe(pd.DataFrame([{
                    "table": v["table"], "field": v["field"], "value": v["value"], "count": v["count"],
                    "allowed": f"{v['allowed_count'][0]}..{v['allowed_count'][1]}",
                    "records to review": v["records"], "reason": v["reason"],
                } for v in count_v]), width="stretch", hide_index=True)
            st.markdown("**Corrections** (choose a valid value for each flagged field)")
            targets = list(dict.fromkeys(c for v in u["violations"] for c in cells(v)))
            if any(not v["records"] for v in count_v):
                st.caption("A count error with no record to change: adjust the fields its conditions use.")
            cols = st.columns(3)
            fixes = {}
            for i, (t, r, f) in enumerate(targets):
                with cols[i % 3]:
                    fixes[(t, r, f)] = correction_widget(u, t, r, f)
            chosen = {f"{t}.{f}" + (f"[{r}]" if r is not None else ""): val for (t, r, f), val in fixes.items() if val not in (None, "")}
            if chosen:
                st.caption("Selected: " + ", ".join(f"{k} = {val}" for k, val in chosen.items()))
        else:
            fixes, chosen = {}, {}
        sfx = f"{u['unit_id']}_{u.get('attempts', 0)}"
        deletions: dict[str, list[int]] = {}
        if u["status"] == "needs_review":
            st.markdown("**Delete related records** (then re-evaluate)")
            # Count errors that disallow a value: suggest deleting the offending records.
            suggest: dict[str, list[int]] = {}
            for v in u["violations"]:
                if v.get("kind") == "count" and v["count"] > v["allowed_count"][1]:
                    suggest.setdefault(v["table"], []).extend(v["records"])
            for child in cfg.children:
                recs = u["draft"].get(child, [])
                if not recs:
                    continue
                pick = st.multiselect(
                    f"{child} records to delete", list(range(len(recs))),
                    default=sorted(set(suggest.get(child, []))), key=f"del_{child}_{sfx}",
                    format_func=lambda i, recs=recs: f"record {i}: " + ", ".join(
                        f"{k}={v}" for k, v in recs[i].items() if "Code" in k or "Name" in k)[:80],
                    help="Pre-selected: records over a count rule's maximum")
                if pick:
                    deletions[child] = pick
            lvl = u["halted_before_level"]
            pending = [(t, r, f) for (t, r, f), val in fixes.items() if val in (None, "")]
            ready = bool(chosen or deletions)
            if st.button(f"Apply changes & re-run from level {lvl}", type="primary", key=f"rerun_{sfx}",
                         disabled=not ready,
                         help="Pick a value or a record to delete first" if not ready else
                         ("Fields left unselected keep their current (invalid) value" if pending else None)):
                payload = [{"table": t, "record": r, "field": f, "value": val}
                           for (t, r, f), val in fixes.items() if val not in (None, "")]
                with st.spinner("Re-running..."):
                    new = generator.rerun_in_file(choice, u["unit_id"], payload, cfg, deletions=deletions)
                st.toast(f"Unit {u['unit_id']}: {new['status']}")
                st.rerun()
        st.markdown(f"**Delete unit** (deletes the {cfg.parent} record and all its related records)")
        confirm = st.checkbox(f"Yes, delete unit {u['unit_id']} ({u['key']})", key=f"confirm_{sfx}")
        if st.button("Delete unit", key=f"delunit_{sfx}", disabled=not confirm):
            generator.delete_unit_in_file(choice, u["unit_id"])
            st.toast(f"Unit {u['unit_id']} deleted")
            st.rerun()
        if u.get("attempts"):
            st.caption(f"Re-run attempts: {u['attempts']}")
        for n in u["notes"]:
            st.caption(n)
        for table, data in u["draft"].items():
            df = show(data)
            st.markdown(f"**{table}**")
            st.dataframe(df.style.apply(highlight(table, u["violations"]), axis=None), width="stretch")

with st.expander("Completed units"):
    for u in by_status("completed"):
        st.markdown(f"**Unit {u['unit_id']} - {u['key']}**")
        for table, data in u["draft"].items():
            st.dataframe(show(data), width="stretch")
