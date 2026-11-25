"""Review UI for generated units.   streamlit run app.py"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import importlib

import count_rules
import generator
import review_logic
import schema

# Streamlit reruns app.py on save but keeps imported modules cached; reload so code changes apply.
for _m in (count_rules, schema, generator, review_logic):
    importlib.reload(_m)
from settings import load_config
import Schemafetcher  # DBHandler (path added by settings)
import formats
from source import load_db_formats

import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # MultiAgent root -> Supervisor package
import Supervisor.audit, Supervisor.repair, Supervisor.graph  # noqa: E401,E402  (LangGraph multi-agent supervisor)
for _m in (Supervisor.audit, Supervisor.repair, Supervisor.graph):
    importlib.reload(_m)
sv = Supervisor.graph

st.set_page_config(page_title="Draft review", layout="wide")
try:
    cfg = load_config()
except (Schemafetcher.SchemaError, ValueError) as e:
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

    def _new_run(spinner: str) -> None:
        for k in [k for k in st.session_state if str(k).startswith(("showdel_", "showedit_", "showdelunit_", "dd_"))]:
            st.session_state.pop(k, None)
        with st.spinner(spinner):
            sv.start(units=int(units), seed=int(seed) or None, per_key=per_key)
        st.rerun()

    # Runs only on click; disabled until every related table is configured.
    if st.button("Execute", type="primary", disabled=bool(problems),
                 help="Fill in min and max for every related table first" if problems else None):
        _new_run("Supervisor: generate -> repair -> LLM ...")
    files = sorted(Path(cfg.output_dir).glob("run_*.json"), reverse=True)
    choice = st.selectbox("Run file", files, format_func=lambda p: p.stem) if files else None
    # Once the selected run is finished: one new run with the sidebar settings and the SAVED feedback weights.
    try:
        _choice_done = choice is not None and generator.run_done(json.loads(Path(choice).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        _choice_done = False
    if _choice_done and st.button("Run again", disabled=bool(problems),
                                  help=("Fill in min and max for every related table first" if problems else
                                        "Starts ONE new run with the sidebar settings and the saved LLM feedback "
                                        "weights (press Save in 'LLM feedback' first); existing runs are untouched.")):
        _new_run("Running again (new run with the saved weights, supervised)...")

import weights as fb_weights  # noqa: E402
from streamlit_sortables import sort_items  # noqa: E402

importlib.reload(fb_weights)

# --------------------------------------------------------------------------- LLM feedback weights (next run)
# Shown only once the selected run is FINISHED (every unit through, after your corrections) - its outcome is
# then merged into the feedback list, which you weigh before simulating the next round.
_sel = json.loads(Path(choice).read_text(encoding="utf-8")) if choice is not None else None
_done = _sel is not None and generator.run_done(_sel)
if _done and not _sel.get("feedback_collected"):
    generator.collect_if_done(choice)
if _sel is not None and not _done:
    _left = sum(1 for u in _sel["units"] if u["status"] != "completed")
    st.caption(f"LLM feedback appears once every unit of this run has gone through ({_left} still to correct "
               "or delete); the run's final outcome is then added to the list for the next round.")
if _done:
    with st.expander("LLM feedback - weigh the LLM's pairs for the next run", expanded=False):
        st.caption("Weightage: **-1** never · **0** no preference · **+1** always (fractions = approximate share). "
                   "Collected from every run's A) conversions and B) count decisions into LLMEffects/LLMfeedback.json; "
                   "used only by NEW runs, never on existing records. Pairs at -1/+1 are never overwritten by new runs.")
        try:
            FB = fb_weights.load_feedback()
        except Exception as e:  # unreadable file: show why, keep the page usable
            FB = None
            st.error(f"LLMfeedback.json is not readable: {e}")
        if FB is not None:
            VAL, CNT = FB["Value-based"], FB["Count-based"]
            weight_col = st.column_config.NumberColumn("Weightage", min_value=-1.0, max_value=1.0, step=0.05,
                                                       format="%.2f", help="-1 never, 0 no preference, +1 always")
            v_opt_col = st.column_config.SelectboxColumn(
                "Options", options=["Remove", "Archive"], width="small",
                help="Remove + Save deletes this pair. Archive: hidden in the React UI's list, still applied at its "
                     "priority")
            c_opt_col = st.column_config.SelectboxColumn(
                "Options", options=["Remove", fb_weights.ONLY, fb_weights.MAX], width="medium",
                help=f"Remove: deleted on Save. '{fb_weights.ONLY}': exactly Count records with that value in ~share "
                     "of the units with this parent value - share PREDICTED from the value pairs that convert into the "
                     f"parent value (own Weightage not used). '{fb_weights.MAX}': AT MOST Count (the value is optional) "
                     "- share = predicted share x this pair's Weightage. The row moves to its section at once; "
                     "Save to keep it. Clear the cell to switch it off.")
            prio_col = st.column_config.NumberColumn("Priority", min_value=1, step=1, width="small",
                                                     help="Type a position to move the row there (applied on Save)")
            CATS = ["Always (1)", "Never (-1)", "No pref (0)", "Positive (0..1)", "Negative (-1..0)"]

            def _cat(w: float) -> str:
                return ("Always (1)" if w >= 1 else "Never (-1)" if w <= -1 else "No pref (0)" if w == 0
                        else "Positive (0..1)" if w > 0 else "Negative (-1..0)")
            show = st.pills("Show weightage", CATS, selection_mode="multi", key="fb_filter",
                            help="Nothing selected = show all. Save before changing the filter (unsaved edits reset).")
            ftag = "-".join(str(i) for i in sorted(CATS.index(c) for c in show)) or "all"
            t_val, t_cnt = st.tabs([f"Value-based ({len(VAL)})", f"Count-based ({len(CNT)})"])

            def _two_col_editor(kind: str, df: pd.DataFrame, editable: set[str], config: dict) -> pd.DataFrame:
                """One table sized to its rows. The frame index is the record's position in the file, so edits map back
                to the full records."""
                if show:  # weightage filter; hidden rows are kept unchanged on save
                    df = df[df["Weightage"].map(lambda w: _cat(float(w))).isin(show)]
                if df.empty:
                    st.caption("No pairs match the filter.")
                    return df
                parts = [df]
                out = []
                for i, (col, part) in enumerate(zip(st.columns(len(parts)), parts)):
                    if part.empty:
                        continue
                    with col:
                        out.append(st.data_editor(part, key=f"fb_{kind}_{i}_{ftag}", hide_index=True, width="stretch",
                                                  height=35 * (len(part) + 1) + 3, column_config=config,
                                                  disabled=[c for c in part.columns if c not in editable]))
                return pd.concat(out) if out else df

            # Count pairs: one table per Options state, because Streamlit can disable columns but not single rows.
            C_GROUPS = [  # (Options value, key tag, title, editable columns)
                (None, "pairs", "Weighted pairs",
                 {"Options", "Priority", "value", "RelatedFieldValue", "Count", "Weightage"}),
                (fb_weights.ONLY, "only", f"{fb_weights.ONLY} - exactly Count; share predicted from the value pairs "
                                          "into the parent value (only Options editable)", {"Options"}),
                (fb_weights.MAX, "max", f"{fb_weights.MAX} - at most Count; share = predicted share x Weightage "
                                        "(only Options and Weightage editable)", {"Options", "Weightage"}),
                ("Remove", "remove", "Marked for removal - deleted on Save (only Options editable, to undo)",
                 {"Options"}),
            ]

            def _opt(o) -> str | None:
                return None if o is None or pd.isna(o) or str(o) == "" else str(o)

            def _cnt_moved(key: str) -> None:
                """An Options change moves the row to another section: carry every count table's unsaved edits over
                (fb_counts_stash, cleared on Save) and rebuild the tables."""
                changed = (st.session_state.get(key) or {}).get("edited_rows") or {}
                if not any("Options" in c for c in changed.values()):
                    return
                stash = st.session_state.setdefault("fb_counts_stash", {})
                for k in st.session_state.get("fb_counts_keys", []):
                    pos = st.session_state.get(f"{k}__pos", [])
                    for i, c in ((st.session_state.get(k) or {}).get("edited_rows") or {}).items():
                        stash.setdefault(pos[int(i)], {}).update(c)
                st.session_state["fb_counts_ver"] = st.session_state.get("fb_counts_ver", 0) + 1

            def _count_editor(df: pd.DataFrame, config: dict) -> pd.DataFrame:
                """The count pairs, one section per Options state; the frame index is the record's file position."""
                if show:  # weightage filter; hidden rows are kept unchanged on save
                    df = df[df["Weightage"].map(lambda w: _cat(float(w))).isin(show)]
                if df.empty:
                    st.caption("No pairs match the filter.")
                    return df
                ver, keys, out = st.session_state.get("fb_counts_ver", 0), [], []
                grp = [_opt(o) for o in df["Options"]]
                for opt, tag, title, editable in C_GROUPS:
                    part = df[[g == opt for g in grp]]
                    if part.empty:
                        continue
                    key = f"fb_counts_{tag}_{ver}_{ftag}"
                    st.session_state[f"{key}__pos"] = list(part.index)
                    keys.append(key)
                    st.caption(f"**{title}** ({len(part)})")
                    out.append(st.data_editor(part, key=key, hide_index=True, width="stretch",
                                              height=35 * (len(part) + 1) + 3, column_config=config,
                                              disabled=[c for c in part.columns if c not in editable],
                                              on_change=_cnt_moved, args=(key,)))
                st.session_state["fb_counts_keys"] = keys
                return pd.concat(out) if out else df

            def _seen(r: dict) -> str:
                """'20261124_205420 (4)' - the last run that produced the pair, and how often it was seen."""
                return f"{r.get('LastRun') or '-'} ({int(r.get('Seen') or 0)})"

            with t_val:
                vdf = pd.DataFrame({
                    "Options": pd.Series([r.get("Option") if r.get("Option") == "Archive" else None for r in VAL],
                                         dtype="object"),  # keep Archive on Save
                    "Priority": range(1, len(VAL) + 1),
                    "Table / Field / current value": [f"{r['Table']} / {r['Field']} / {r['current_value']}" for r in VAL],
                    "LLM_value": [str(r["LLM_value"]) for r in VAL],
                    "Weightage": [float(r.get("Weightage") or 0) for r in VAL],
                    "Last run (seen)": [_seen(r) for r in VAL]})
                v_edit = _two_col_editor("values", vdf, {"Options", "Priority", "LLM_value", "Weightage"}, {
                    "Options": v_opt_col,
                    "Priority": prio_col, "Weightage": weight_col,
                    "LLM_value": st.column_config.TextColumn("LLM_value", help="Editable: set a custom value")})
            with t_cnt:
                c_rows = [{
                    "Options": fb_weights.option(r),
                    "Priority": i + 1,
                    "Field / RelatedField": f"{r['Field']} / {r['RelatedField']}",
                    "value": str(r.get("value")),
                    "RelatedFieldValue": str(r.get("RelatedFieldValue")),
                    "Count": int(r.get("Count") or 0),
                    "Weightage": float(r.get("Weightage") or 0),
                    "Note": r.get("Note") or "",
                    "Last run (seen)": _seen(r)} for i, r in enumerate(CNT)]
                for pos, ch in st.session_state.get("fb_counts_stash", {}).items():  # unsaved edits of moved rows
                    if pos < len(c_rows):
                        c_rows[pos].update(ch)
                cdf = pd.DataFrame(c_rows, columns=list(c_rows[0]) if c_rows else ["Options", "Priority", "Weightage"])
                cdf["Options"] = cdf["Options"].astype(object)
                c_edit = _count_editor(cdf, {
                    "Options": c_opt_col,
                    "Priority": prio_col, "Weightage": weight_col,
                    "value": st.column_config.TextColumn("value", help="Editable: the parent field's value"),
                    "RelatedFieldValue": st.column_config.TextColumn("RelatedFieldValue",
                                                                     help="Editable: the related field's value"),
                    "Count": st.column_config.NumberColumn("Count", min_value=0, step=1,
                                                           help="Number of related records with that value")})

            def _merge(orig: list[dict], edited: pd.DataFrame, fields: list[str]) -> list[dict]:
                """Edited cells back onto ALL records (rows hidden by the filter stay as they are), ordered by Priority
                (a moved row goes before a tie)."""
                edits = {pos: r for pos, r in edited.iterrows()}
                rows = []
                for pos, base in enumerate(orig):
                    rec, prio = dict(base), float(pos + 1)
                    if pos in edits:
                        r = edits[pos]
                        opt = r.get("Options")
                        opt = None if opt is None or pd.isna(opt) or str(opt) == "" else str(opt)
                        if opt == "Remove":
                            continue  # chosen for removal: dropped from the list on save
                        if opt:
                            rec["Option"] = opt
                        else:
                            rec.pop("Option", None)
                        for f in fields:
                            rec[f] = None if pd.isna(r[f]) else r[f]
                        prio = prio if pd.isna(r["Priority"]) else float(r["Priority"])
                    rows.append((prio, 0 if prio != pos + 1 else 1, pos, rec))
                return [rec for *_, rec in sorted(rows, key=lambda x: x[:3])]

            def _save(values: list[dict] | None = None, counts: list[dict] | None = None) -> None:
                vals = values if values is not None else _merge(VAL, v_edit, ["LLM_value", "Weightage"])
                cnts = counts if counts is not None else _merge(CNT, c_edit, ["value", "RelatedFieldValue", "Count",
                                                                              "Weightage"])
                for r in vals + cnts:
                    r["Weightage"] = float(r.get("Weightage") or 0)
                for r in cnts:
                    r["Count"] = int(r.get("Count") or 0)
                fb_weights.save_feedback({"Value-based": vals, "Count-based": cnts})
                for k in [k for k in st.session_state if str(k).startswith(("fb_values_", "fb_counts_"))]:
                    st.session_state.pop(k, None)  # edits are row-indexed: restart the editors on the saved order

            def _prioritizer(kind: str, rows: list[dict], label) -> None:
                """Optional drag list; dropping a row saves the new order right away."""
                if not rows or not st.toggle("Prioritize by dragging", key=f"tog_{kind}"):
                    return
                labels = [f"{i + 1}. {label(r)}" for i, r in enumerate(rows)]
                new = sort_items(labels, direction="vertical", key=f"sort_{kind}_{abs(hash(tuple(labels)))}")
                if new != labels:
                    ordered = [rows[labels.index(x)] for x in new]
                    _save(**({"values": ordered} if kind == "values" else {"counts": ordered}))
                    st.rerun()

            with t_val:
                _prioritizer("values", _merge(VAL, v_edit, ["LLM_value", "Weightage"]),
                             lambda r: f"{r['Table']} / {r['Field']} / {r['current_value']} -> {r['LLM_value']}"
                                       f"   (w {float(r['Weightage'] or 0):+.2f})")
            with t_cnt:
                _prioritizer("counts", _merge(CNT, c_edit, ["value", "RelatedFieldValue", "Count", "Weightage"]),
                             lambda r: f"{r['Field']}={r['value']} / {r['RelatedField']}={r['RelatedFieldValue']} "
                                       f"x{r['Count']}   (" + (fb_weights.ONLY if fb_weights.is_only(r) else
                                                               (f"{fb_weights.MAX}, " if fb_weights.is_max(r) else "")
                                                               + f"w {float(r['Weightage'] or 0):+.2f}") + ")")
            st.caption("Priority: earlier pairs are considered first - type a new number in Priority and Save, or drag. "
                       "Value pairs act while a field is filled; count pairs act after that.")

            if st.button("Save", type="primary", key="fb_save",
                         help="Saves weights, values, priorities and removals; 'Run again' in the sidebar uses them"):
                _save()
                st.toast("LLM feedback saved - the next run uses it")
                st.rerun()

if choice is None:
    st.info("No runs yet. Fill in the related tables and press 'Execute' in the sidebar, or run `python generator.py`.")
    st.stop()

run = json.loads(Path(choice).read_text(encoding="utf-8"))
units_ = run["units"]
by_status = lambda s: [u for u in units_ if u["status"] == s]  # noqa: E731

for w in run["warnings"]:
    st.warning(w)

_rv = Path(choice).parent / f"llm_review_{run['run_id']}.json"
try:
    LLM = {u["unit_id"]: u for u in json.loads(_rv.read_text(encoding="utf-8"))["units"]} if _rv.exists() else {}
except (OSError, KeyError, json.JSONDecodeError):
    LLM = {}
    st.warning(f"LLM review file not readable ({_rv.name})")


def llm_for(u: dict) -> dict | None:
    """The LLM review of this unit's current attempt (older attempts are stale)."""
    return review_logic.llm_for(LLM, u)


def llm_values(u: dict) -> dict:
    """(table, record, field) -> value proposed by the LLM (conversions + count decisions)."""
    return review_logic.llm_values(llm_for(u))

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

# ---- Supervisor (multi-agent): agent trace + end-of-round audit (read-only) -----------------------------
_sv = run.get("supervisor") or {}
_aud = run.get("audit") or {}
_n_viol = sum(v["violations"] for v in (_aud.get("summary") or {}).values())
with st.expander(f"Supervisor (multi-agent) - round {_sv.get('round', '-')}, status: {_sv.get('status') or 'not supervised'}"
                 + (f" - audit: {_n_viol} violation(s)" if _aud else ""), expanded=bool(_aud and _n_viol)):
    if not _sv:
        st.caption("This run was not started through the supervisor (use Execute).")
    else:
        st.caption("Agents: generate (Agent 1, rules) -> repair (B, swaps related sets between halted units, no LLM) "
                   "-> llm (Agent 2) -> await_human (Agent 3, UI) -> audit (A, once every unit is completed). "
                   "The supervisor routes by rules and makes no LLM call.")
        st.markdown("**Agent trace**")
        st.dataframe(pd.DataFrame(_sv.get("trace", [])), width="stretch", hide_index=True)
        st.markdown("**Audit** (end of round - report only, nothing is changed)")
        if not _aud:
            st.caption("Not audited yet: the audit runs when every unit of the round is completed.")
        else:
            cols = st.columns(len(_aud["summary"]))
            for col, (author, s) in zip(cols, _aud["summary"].items()):
                col.metric(f"{author} violations", s["violations"], help=f"{s['checks']} check(s)")
            st.caption(f"Round {_aud['round']}, audited {_aud['at']}")
            _df = pd.DataFrame(_aud["findings"])
            if _df.empty:
                st.caption("No authored changes in this run.")
            else:
                only = st.toggle("Show violations only", value=True, key="audit_only_viol")
                if only:
                    _df = _df[_df["verdict"] == "violation"]
                _df = _df.astype("string")
                st.dataframe(_df.style.apply(lambda r: ["background-color: #f8b4b4" if r["verdict"] == "violation"
                                                        else "" for _ in r], axis=1),
                             width="stretch", hide_index=True)

st.subheader("All units")
st.dataframe(pd.DataFrame([{
    "unit": u["unit_id"], "key": u["key"], "status": u["status"], "levels_done": u["levels_done"],
    "halted_before_level": u["halted_before_level"],
    "field errors": sum(1 for v in u["violations"] if v.get("kind", "field") == "field"),
    "count errors": sum(1 for v in u["violations"] if v.get("kind") == "count"),
} for u in units_]), width="stretch", hide_index=True)

st.subheader("Needs manual review")
flagged = by_status("needs_review") + by_status("error")
_with_a = [u["unit_id"] for u in by_status("needs_review") if (llm_for(u) or {}).get("conversions")]
if _with_a:
    if st.button(f"Apply LLM conversions (A) to all {len(_with_a)} unit(s) & re-run", type="primary",
                 help="Writes each unit's A) conversions into its draft and re-runs it from the halted level. "
                      "B) count decisions and C) suggestions are not applied."):
        with st.spinner("Applying LLM conversions and re-running..."):
            res = generator.apply_llm_conversions(choice, _with_a, cfg)
        st.toast(", ".join(f"unit {k}: {v}" for k, v in res.items()) or "Nothing applied")
        st.rerun()
if not flagged:
    st.success("Nothing to review.")


def show(data) -> pd.DataFrame:
    """Draft records as text: CSV values (str) and generated ones (int) can share a column."""
    return pd.DataFrame(data if isinstance(data, list) else [data]).astype("string")


cells = review_logic.cells  # (table, record, field) a reviewer can change for one violation
LIST_FIELDS = fb_weights._feedback_module().list_fields()  # only these can go into LLM feedback


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


def allowed_for(table: str, fld: str, ctx: dict) -> tuple[str, object, bool] | None:
    """(kind, spec, scoped) from registry_dump.json for this row context (see review_logic.allowed_for)."""
    return review_logic.allowed_for(RULES, table, fld, ctx)


_MISSING = review_logic.MISSING
cell_value = review_logic.cell_value  # current draft value of a (table, record, field), or _MISSING


DBF = load_db_formats(cfg)  # target -> db_format from mapping.json


def date_widget(label: str, key: str, proposed, fmt: str, lo=None, hi=None, help_: str | None = None):
    """Calendar picker; the picked date is returned in the field's format (e.g. YYYY-MM-DD / YYYYMMDD)."""
    d = formats.parse_date(proposed) if proposed not in (None, "") else None
    picked = st.date_input(label, value=d.date() if d else None, min_value=lo, max_value=hi, key=key,
                           format="YYYY-MM-DD", help=help_ or f"Stored as {fmt}")
    return picked.strftime(formats.DATE_FORMATS[fmt]) if picked else None


@st.dialog("Add to LLM feedback", width="large")
def feedback_dialog(u: dict, v: dict, dd_key: str) -> None:
    """Confirm (and correct) a unit's error as a value or count pair before it goes into LLMfeedback.json."""
    rv = llm_for(u) or {}
    t, f = v["table"], v["field"]
    if v.get("kind", "field") == "field":
        st.markdown("**Value-based pair**")
        c1, c2, c3 = st.columns(3)
        c1.text_input("Table", t, disabled=True)
        c2.text_input("Field", f, disabled=True)
        c3.text_input("current_value", str(v["value"]), disabled=True)
        proposed = llm_values(u).get((t, v["record"], f))
        to = st.text_input("LLM_value", "" if proposed is None else str(proposed),
                           help="Prefilled from the LLM's A) proposal when there is one - change it if it's wrong")
        w = st.slider("Weightage", -1.0, 1.0, 1.0, 0.05, help="-1 never, 0 no preference, +1 always")
        cur = v["value"]
        row = {"Table": t, "Field": f, "Type": "number" if isinstance(cur, (int, float)) and not isinstance(cur, bool)
               else "text", "current_value": cur, "LLM_value": to, "Weightage": w, "Seen": 0, "Note": "added from UI"}
        section, ok = "Value-based", bool(to.strip())
    else:
        st.markdown("**Count-based pair**")
        prow = u["draft"][cfg.parent]
        options = [f"{cfg.parent}.{k}" for k in prow if k != cfg.key_field and f"{cfg.parent}.{k}" in LIST_FIELDS]
        related = f"{t}.{f}"
        hint = next((c.get("parent_field") for c in rv.get("count_decisions") or []
                     if c.get("count_field") == related and c.get("parent_field") in options), None)
        c1, c2 = st.columns(2)
        pf = c1.selectbox("Field (parent)", options, index=options.index(hint) if hint else None,
                          placeholder="Which parent field does this count depend on?",
                          help="Prefilled from the LLM's B) decision when there is one")
        pval = c2.text_input("value", "" if pf is None else str(prow.get(pf.split(".", 1)[1], "")))
        c3, c4, c5 = st.columns(3)
        c3.text_input("RelatedField", related, disabled=True)
        rfv = c4.text_input("RelatedFieldValue", str(v["value"]))
        cnt = c5.number_input("Count", min_value=0, value=int(v.get("count", 0)), step=1)
        w = st.slider("Weightage", -1.0, 1.0, -1.0, 0.05, help="-1 never, 0 no preference, +1 always")
        row = {"RelatedTable": t, "RelatedField": related, "RelatedFieldValue": rfv, "Field": pf, "value": pval,
               "Count": int(cnt), "Weightage": w, "Note": "added from UI", "Seen": 0}
        section, ok = "Count-based", bool(pf and rfv.strip())
    never = w <= -1
    if never:
        st.warning(f"Never (-1): on Confirm, unit {u['unit_id']} ({u['key']}) is REMOVED from this run; its data "
                   "is kept as JSON with this pair in LLMfeedback.json.")
    st.caption("Added at the bottom of the list (lowest priority) - move it up in the LLM feedback section. "
               "Used only by NEW runs.")
    b1, b2, _ = st.columns([1.4, 1, 3])
    if b1.button("Confirm & remove unit" if never else "Confirm", type="primary", disabled=not ok):
        meta = None
        if never:  # keep the removed unit's data with the pair, then drop the unit from the run
            meta = {"run_id": run["run_id"], "unit_id": u["unit_id"], "key": u["key"], "status": u["status"],
                    "halted_before_level": u["halted_before_level"], "attempts": u.get("attempts", 0),
                    "violations": u["violations"], "draft": u["draft"], "removed_at": pd.Timestamp.now().isoformat()}
        fb_weights.add_pair(section, row, meta)  # an existing identical pair is updated in place
        if never:
            generator.delete_unit_in_file(choice, u["unit_id"])
        st.session_state.pop(dd_key, None)
        st.toast(f"Added to LLM feedback ({section})" + (f"; unit {u['unit_id']} removed" if never else ""))
        st.rerun()
    if b2.button("Cancel"):
        st.session_state.pop(dd_key, None)
        st.rerun()


def correction_widget(u: dict, table: str, rec: int | None, fld: str, proposed=None, short: bool = False):
    row = u["draft"][table] if rec is None else u["draft"][table][rec]
    ctx = {cfg.parent: u["draft"][cfg.parent], table: row}
    key = f"fix_{u['unit_id']}_{u.get('attempts', 0)}_{table}_{rec}_{fld}"
    label = fld if short else f"{table}.{fld}" + (f" [record {rec}]" if rec is not None else "")
    hint = f"current: {row.get(fld)!r}"
    if proposed is not None:
        label += " (LLM)"
    found = allowed_for(table, fld, ctx)
    db_fmt = formats.norm(DBF.get(f"{table}.{fld}"))
    if found is None:
        if formats.is_date_format(db_fmt):
            return date_widget(label, key, proposed, db_fmt, help_=f"No rule; stored as {db_fmt} (db_format)")
        return st.text_input(label, value="" if proposed is None else str(proposed), key=key, placeholder=hint, help="No rule in registry_dump.json - free text")
    kind, spec, scoped = found
    # Override: type any value, bypassing the rule-limited dropdown / range (re-validated on re-run).
    if st.checkbox("override", key=f"ovr_{key}", help=f"Type a custom value instead of the rule's options ({spec})"):
        raw = st.text_input(label + " - custom", value="" if proposed is None else str(proposed),
                            key=f"{key}_custom", placeholder=hint,
                            help="Custom value; the rules are checked again when the unit is re-run")
        if kind in ("RangeInt", "Range_YYYYMM", "Range_YYYYMMDD") and raw.strip().lstrip("-").isdigit():
            return int(raw)
        return raw
    if kind in ("Range_YYYYMMDD", "Range_YYYYMM"):  # rule = calendar bounds; value stored in the DB type
        pat = "YYYYMMDD" if kind == "Range_YYYYMMDD" else "YYYYMM"
        lo, hi = (formats.parse_date(str(x), pat) for x in spec)
        fmt = db_fmt if formats.is_date_format(db_fmt) else "YYYY-MM-DD"
        return date_widget(label, key, proposed, fmt, lo.date() if lo else None, hi.date() if hi else None,
                           help_=f"Allowed {spec[0]} .. {spec[1]} (bounds only); stored as {fmt}")
    if kind == "Range_C" and formats.is_date_format(db_fmt):
        return date_widget(label, key, proposed, db_fmt, help_=f"Rule: {spec}; stored as {db_fmt}")
    if kind == "ListStr":
        help_ = None if scoped else "No rule branch matches the current values of the fields it depends on - showing all options"
        idx = spec.index(proposed) if proposed in spec else None
        return st.selectbox(label, spec, index=idx, key=key, placeholder=hint, help=help_)
    if kind in ("RangeInt", "Range_YYYYMM", "Range_YYYYMMDD"):
        try:
            val = int(proposed) if proposed is not None and spec[0] <= int(proposed) <= spec[1] else None
        except (TypeError, ValueError):
            val = None
        return st.number_input(label, min_value=spec[0], max_value=spec[1], value=val, step=1, key=key,
                               placeholder=hint, help=f"Allowed {spec[0]} .. {spec[1]}" + ({"Range_YYYYMM": " (YYYYMM)", "Range_YYYYMMDD": " (YYYYMMDD, real date)"}.get(kind, "")))
    return st.text_input(label, value="" if proposed is None else str(proposed), key=key, placeholder=hint, help=f"Rule: {spec}")


for u in flagged:
    stage = f"halted before level {u['halted_before_level']}" if u["halted_before_level"] is not None else u["status"]
    rv = llm_for(u)
    tag = f" - LLM: {rv['status']}" if rv else ""
    with st.expander(f"Unit {u['unit_id']} - {u['key']} - {u['status']} ({stage}){tag}"):
        sfx = f"{u['unit_id']}_{u.get('attempts', 0)}"
        # Records to pre-select for deletion: over a count rule's maximum, or LLM delete proposals.
        suggest: dict[str, list[int]] = {}
        for v in u["violations"]:
            if v.get("kind") == "count" and v["count"] > v["allowed_count"][1]:
                suggest.setdefault(v["table"], []).extend(v["records"])
        for c in (rv or {}).get("count_decisions") or []:
            if c.get("field") == "__delete__" and isinstance(c.get("record"), int):
                suggest.setdefault(c.get("table"), []).append(c["record"])

        # ---- header: summary left, action buttons top right
        related = [ch for ch in cfg.children if u["status"] == "needs_review" and u["draft"].get(ch)]
        head = st.columns([4, 2, 2, 2, 1.4] if related else [7, 2, 1.4])
        head[0].markdown(f"**Unit {u['unit_id']} - {u['key']}** · {u['status']} ({stage})"
                         + (f" · re-run attempts: {u['attempts']}" if u.get("attempts") else ""))
        if related:
            # Edit: brings a related table's count-error fields back into Edit even when deletion is proposed.
            # Delete: opens the delete section for a table that has no count error / LLM delete proposal.
            for col, kind, label in ((head[1], "showedit", "Edit related tables"),
                                     (head[2], "showdel", "Delete related tables")):
                opts = [ch for ch in related if not st.session_state.get(f"{kind}_{ch}_{sfx}")
                        and not (kind == "showdel" and suggest.get(ch))]
                pick = col.selectbox(label, opts, index=None, placeholder=label, label_visibility="collapsed",
                                     key=f"dd_{kind}_{sfx}", disabled=not opts)
                if pick:
                    st.session_state[f"{kind}_{pick}_{sfx}"] = True
                    st.session_state.pop(f"dd_{kind}_{sfx}", None)
                    st.rerun()
        # Add one of this unit's errors to the LLM feedback list (confirmed in a popup first).
        errs = {f"{'count' if v.get('kind') == 'count' else 'value'}: {v['table']}.{v['field']}"
                + (f"[{v['record']}]" if v.get("record") is not None else "") + f" = {v['value']!r}": v
                for v in u["violations"] if f"{v['table']}.{v['field']}" in LIST_FIELDS}  # list-type fields only
        fb_key = f"dd_fb_{sfx}"
        fb_pick = head[-2].selectbox("Add error to LLM feedback", list(errs), index=None,
                                     placeholder="Add error to LLM feedback", label_visibility="collapsed",
                                     key=fb_key, disabled=not errs)
        if fb_pick:
            feedback_dialog(u, errs[fb_pick], fb_key)
        uflag = f"showdelunit_{sfx}"
        if head[-1].button("Remove unit", key=f"btn_{uflag}", width="stretch"):
            st.session_state[uflag] = True
            st.rerun()
        if st.session_state.get(uflag):
            st.markdown(f"**Delete unit** (deletes the {cfg.parent} record and all its related records)")
            confirm = st.checkbox(f"Yes, delete unit {u['unit_id']} ({u['key']})", key=f"confirm_{sfx}")
            c1, c2, _ = st.columns([1, 1, 6])
            if c1.button("Delete unit", key=f"delunit_{sfx}", disabled=not confirm, type="primary"):
                generator.delete_unit_in_file(choice, u["unit_id"])
                st.session_state.pop(uflag, None)
                st.toast(f"Unit {u['unit_id']} deleted")
                st.rerun()
            if c2.button("Cancel", key=f"cancelunit_{sfx}"):
                st.session_state.pop(uflag, None)
                st.rerun()

        # ---- the unit's records first
        for table, data in u["draft"].items():
            st.markdown(f"**{table}**")
            st.dataframe(show(data).style.apply(highlight(table, u["violations"]), axis=None), width="stretch")
        if u["notes"]:
            with st.popover("Notes"):
                for n in u["notes"]:
                    st.caption(n)
        st.divider()

        # ---- errors / LLM review / edit below
        applied = u.get("llm_applied") or []
        if applied:
            st.markdown("**A) LLM conversions applied automatically** (still editable below)")
            st.dataframe(pd.DataFrame(applied).astype("string"), width="stretch", hide_index=True)
        if rv:
            st.markdown(f"**LLM review of this halt** ({rv['status']}, {rv['rounds']} round(s), "
                        f"trigger: {rv.get('trigger', 'run')})")
            for title, k in (("B) Count decisions", "count_decisions"),
                             ("C) Suggestions (prefilled in Edit - applied only when you re-run)", "suggestions")):
                if rv.get(k):
                    st.caption(title)
                    st.dataframe(pd.DataFrame(rv[k]).astype("string"), width="stretch", hide_index=True)
            if rv.get("conflicts"):
                st.caption("Conflicts: " + "; ".join(rv["conflicts"]))
            if rv.get("remaining_violations"):
                st.caption(f"Still failing after the LLM fixes: {len(rv['remaining_violations'])} violation(s)")
            _pend = [c for c in rv.get("conversions") or [] if cell_value(u, c) is not _MISSING
                     and cell_value(u, c) != c.get("to")]
            if _pend and u["status"] == "needs_review":
                st.caption("A) conversions not applied yet: " + ", ".join(
                    f"{c['table']}.{c['field']}={c['to']!r}" for c in _pend))
                if st.button("Apply LLM conversions (A) & re-run", key=f"llmA_{u['unit_id']}_{u.get('attempts', 0)}"):
                    with st.spinner("Applying LLM conversions and re-running..."):
                        res = generator.apply_llm_conversions(choice, [u["unit_id"]], cfg)
                    st.toast(f"Unit {u['unit_id']}: {res.get(u['unit_id'], 'nothing applied')}")
                    st.rerun()
        elif u["status"] == "needs_review":
            st.caption("No LLM review for this attempt (disabled, failed, or still running) - see LLMEffects/logs.")
        fixes, chosen = {}, {}
        if u["violations"] or applied or (rv or {}).get("suggestions"):
            field_v = [v for v in u["violations"] if v.get("kind", "field") == "field"]
            count_v = [v for v in u["violations"] if v.get("kind") == "count"]
            covered = {(c.get("table"), c.get("record"), c.get("field")) for c in (rv or {}).get("conversions") or []}
            uncovered = [v for v in field_v if (v["table"], v["record"], v["field"]) not in covered]
            if uncovered:  # violations the LLM sections above do not already cover
                st.markdown("**Contradicting fields** (registry rules, not covered by the LLM)")
                st.dataframe(pd.DataFrame(uncovered).drop(columns=["kind"], errors="ignore").astype("string"),
                             width="stretch", hide_index=True)
            if count_v and not (rv or {}).get("count_decisions"):
                st.markdown("**Count rule errors** (count_dump.json)")
                st.dataframe(pd.DataFrame([{
                    "table": v["table"], "field": v["field"], "value": v["value"], "count": v["count"],
                    "allowed": f"{v['allowed_count'][0]}..{v['allowed_count'][1]}",
                    "records to review": v["records"], "reason": v["reason"],
                } for v in count_v]), width="stretch", hide_index=True)
            if u["status"] == "needs_review":
                # Edit: flagged fields (prefilled with A/B proposals), C suggestions, and A-applied fields.
                prefill: dict = {}
                for c in applied:
                    prefill.setdefault((c["table"], c["record"], c["field"]), cell_value(u, c))
                for c in (rv or {}).get("suggestions") or []:
                    prefill[(c.get("table"), c.get("record"), c.get("field"))] = c.get("suggested")
                prefill.update(llm_values(u))
                targets = list(dict.fromkeys([c for v in u["violations"] for c in cells(v)] + list(prefill)))
                targets = [tg for tg in targets
                           if cell_value(u, dict(zip(("table", "record", "field"), tg))) is not _MISSING]
                # Count-error fields whose record is already proposed for deletion: handled by the delete section.
                count_cells = {c for v in count_v for c in cells(v)}
                targets = [(t, r, f) for t, r, f in targets
                           if not ((t, r, f) in count_cells and r in suggest.get(t, [])
                                   and not st.session_state.get(f"showedit_{t}_{sfx}"))]
                if targets:
                    st.markdown("**Edit** (prefilled from the LLM: A applied, B/C proposals - change anything)")
                if any(not v["records"] for v in count_v):
                    st.caption("A count error with no record to change: adjust the fields its conditions use.")
                # One line per record: key field | record # | that record's editable fields (records never mixed).
                order = {cfg.parent: -1, **{c: i for i, c in enumerate(cfg.children)}}
                groups: dict = {}
                for t, r, f in targets:
                    groups.setdefault((t, r), []).append(f)
                for (t, r), flds in sorted(groups.items(), key=lambda g: (order.get(g[0][0], 99), g[0][1] or -1)):
                    kf = cfg.key_field if t == cfg.parent else cfg.children.get(t, {}).get("key_field", cfg.key_field)
                    row = u["draft"][t] if r is None else u["draft"][t][r]
                    cols = st.columns([1.3, 0.9] + [2.2] * len(flds))
                    cols[0].text_input(f"{t}.{kf}", value=str(row.get(kf, "")), disabled=True,
                                       key=f"kf_{u['unit_id']}_{u.get('attempts', 0)}_{t}_{r}")
                    cols[1].text_input("record #", value="parent" if r is None else str(r), disabled=True,
                                       key=f"rn_{u['unit_id']}_{u.get('attempts', 0)}_{t}_{r}")
                    for col, f in zip(cols[2:], flds):
                        with col:
                            fixes[(t, r, f)] = correction_widget(u, t, r, f, prefill.get((t, r, f)), short=True)

                def _cur(t, r, f):
                    return cell_value(u, {"table": t, "record": r, "field": f})
                fixes = {k: v for k, v in fixes.items() if v not in (None, "") and str(v) != str(_cur(*k))}
                chosen = {f"{t}.{f}" + (f"[{r}]" if r is not None else ""): val for (t, r, f), val in fixes.items()}
                if chosen:
                    st.caption("Will change on re-run: " + ", ".join(f"{k} = {val}" for k, val in chosen.items()))
        deletions: dict[str, list[int]] = {}
        if u["status"] == "needs_review":
            for child in cfg.children:
                recs = u["draft"].get(child, [])
                if not recs:
                    continue
                # Shown directly when a count error / LLM proposes deletions; otherwise via the header button.
                if not suggest.get(child) and not st.session_state.get(f"showdel_{child}_{sfx}"):
                    continue
                st.markdown(f"**Delete related records - {child}** (then re-evaluate)")
                pick = st.multiselect(
                    f"{child} records to delete", list(range(len(recs))),
                    default=sorted(i for i in set(suggest.get(child, [])) if 0 <= i < len(recs)), key=f"del_{child}_{sfx}",
                    format_func=lambda i, recs=recs: f"record {i}: " + ", ".join(
                        f"{k}={v}" for k, v in recs[i].items() if "Code" in k or "Name" in k)[:80],
                    help="Pre-selected: records over a count rule's maximum, or LLM delete proposals")
                if pick:
                    deletions[child] = pick
            lvl = u["halted_before_level"]
            pending = [v for v in u["violations"] if v.get("kind", "field") == "field"
                       and (v["table"], v["record"], v["field"]) not in fixes]
            ready = bool(chosen or deletions)
            if st.button(f"Apply changes & re-run from level {lvl}", type="primary", key=f"rerun_{sfx}",
                         disabled=not ready,
                         help="Pick a value or a record to delete first" if not ready else
                         ("Flagged fields left unchanged keep their current (invalid) value" if pending else None)):
                payload = [{"table": t, "record": r, "field": f, "value": val} for (t, r, f), val in fixes.items()]
                with st.spinner("Re-running, then supervisor: repair -> LLM -> (wait | audit) ..."):
                    new = generator.rerun_in_file(choice, u["unit_id"], payload, cfg, deletions=deletions, llm=False)
                    sv.resume(choice, trigger="human")  # human feedback done -> next supervised pass
                new = next((x for x in json.loads(Path(choice).read_text(encoding="utf-8"))["units"]
                            if x["unit_id"] == u["unit_id"]), new)
                st.toast(f"Unit {u['unit_id']}: {new['status']}")
                st.rerun()
with st.expander("Completed units"):
    for u in by_status("completed"):
        st.markdown(f"**Unit {u['unit_id']} - {u['key']}**")
        for table, data in u["draft"].items():
            st.dataframe(show(data), width="stretch")
