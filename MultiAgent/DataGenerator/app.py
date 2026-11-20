"""Review UI for generated units.   streamlit run app.py"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import generator
from settings import load_config

st.set_page_config(page_title="Draft review", layout="wide")
cfg = load_config()

st.title("Generated drafts - review")

with st.sidebar:
    st.header("Run")
    units = st.number_input("Units", 1, 500, cfg.units)
    seed = st.number_input("Seed (0 = random)", 0, 10**6, 0)
    if st.button("Generate new run", type="primary"):
        with st.spinner("Generating..."):
            generator.run(load_config(units=int(units), seed=int(seed) or None))
        st.rerun()
    files = sorted(Path(cfg.output_dir).glob("run_*.json"), reverse=True)
    choice = st.selectbox("Run file", files, format_func=lambda p: p.stem) if files else None

if choice is None:
    st.info("No runs yet. Use 'Generate new run' in the sidebar, or run `python generator.py`.")
    st.stop()

run = json.loads(Path(choice).read_text(encoding="utf-8"))
units_ = run["units"]
by_status = lambda s: [u for u in units_ if u["status"] == s]  # noqa: E731

for w in run["warnings"]:
    st.warning(w)

c1, c2, c3, c4 = st.columns(4)
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
    "halted_before_level": u["halted_before_level"], "violations": len(u["violations"]),
} for u in units_]), width="stretch", hide_index=True)

st.subheader("Needs manual review")
flagged = by_status("needs_review") + by_status("error")
if not flagged:
    st.success("Nothing to review.")


def highlight(table: str, violations: list[dict]):
    bad = {(v["record"] or 0, v["field"]) for v in violations if v["table"] == table}

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
    if kind in ("RangeInt", "Range_YYYYMM"):
        return kind, (min(b["allowed"][0] for b in use), max(b["allowed"][1] for b in use)), bool(ok)
    return kind, use[0]["allowed"], bool(ok)


def correction_widget(u: dict, v: dict):
    table, fld, rec = v["table"], v["field"], v["record"]
    row = u["draft"][table] if rec is None else u["draft"][table][rec]
    ctx = {cfg.parent: u["draft"][cfg.parent], table: row}
    key = f"fix_{u['unit_id']}_{u.get('attempts', 0)}_{table}_{rec}_{fld}"
    label = f"{table}.{fld}" + (f" [record {rec}]" if rec is not None else "")
    hint = f"current: {v['value']!r}"
    found = allowed_for(table, fld, ctx)
    if found is None:
        return st.text_input(label, key=key, placeholder=hint, help="No rule in registry_dump.json - free text")
    kind, spec, scoped = found
    if kind == "ListStr":
        help_ = None if scoped else "No rule branch matches the current values of the fields it depends on - showing all options"
        return st.selectbox(label, spec, index=None, key=key, placeholder=hint, help=help_)
    if kind in ("RangeInt", "Range_YYYYMM"):
        return st.number_input(label, min_value=spec[0], max_value=spec[1], value=None, step=1, key=key,
                               placeholder=hint, help=f"Allowed {spec[0]} .. {spec[1]}" + (" (YYYYMM)" if kind == "Range_YYYYMM" else ""))
    return st.text_input(label, key=key, placeholder=hint, help=f"Rule: {spec}")


for u in flagged:
    stage = f"halted before level {u['halted_before_level']}" if u["halted_before_level"] is not None else u["status"]
    with st.expander(f"Unit {u['unit_id']} - {u['key']} - {u['status']} ({stage})"):
        if u["violations"]:
            st.markdown("**Contradicting fields**")
            st.dataframe(pd.DataFrame(u["violations"]), width="stretch", hide_index=True)
            st.markdown("**Corrections** (choose a valid value for each flagged field)")
            cols = st.columns(3)
            fixes = {}
            for i, v in enumerate(u["violations"]):
                with cols[i % 3]:
                    fixes[(v["table"], v["record"], v["field"])] = correction_widget(u, v)
            chosen = {f"{t}.{f}" + (f"[{r}]" if r is not None else ""): val for (t, r, f), val in fixes.items() if val not in (None, "")}
            if chosen:
                st.caption("Selected: " + ", ".join(f"{k} = {val}" for k, val in chosen.items()))
            if u["status"] == "needs_review":
                lvl = u["halted_before_level"]
                pending = [(t, r, f) for (t, r, f), val in fixes.items() if val in (None, "")]
                if st.button(f"Apply corrections & re-run from level {lvl}", type="primary",
                             key=f"rerun_{u['unit_id']}_{u.get('attempts', 0)}",
                             disabled=not chosen,
                             help="Fix at least one field first" if not chosen else
                             ("Fields left unselected keep their current (invalid) value" if pending else None)):
                    payload = [{"table": t, "record": r, "field": f, "value": val}
                               for (t, r, f), val in fixes.items() if val not in (None, "")]
                    with st.spinner("Re-running..."):
                        new = generator.rerun_in_file(choice, u["unit_id"], payload, cfg)
                    st.toast(f"Unit {u['unit_id']}: {new['status']}")
                    st.rerun()
        if u.get("attempts"):
            st.caption(f"Re-run attempts: {u['attempts']}")
        for n in u["notes"]:
            st.caption(n)
        for table, data in u["draft"].items():
            df = pd.DataFrame(data if isinstance(data, list) else [data])
            st.markdown(f"**{table}**")
            st.dataframe(df.style.apply(highlight(table, u["violations"]), axis=None), width="stretch")

with st.expander("Completed units"):
    for u in by_status("completed"):
        st.markdown(f"**Unit {u['unit_id']} - {u['key']}**")
        for table, data in u["draft"].items():
            st.dataframe(pd.DataFrame(data if isinstance(data, list) else [data]), width="stretch")
