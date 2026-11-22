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

_rv = Path(choice).parent / f"llm_review_{run['run_id']}.json"
try:
    LLM = {u["unit_id"]: u for u in json.loads(_rv.read_text(encoding="utf-8"))["units"]} if _rv.exists() else {}
except (OSError, KeyError, json.JSONDecodeError):
    LLM = {}
    st.warning(f"LLM review file not readable ({_rv.name})")


def llm_for(u: dict) -> dict | None:
    """The LLM review of this unit's current attempt (older attempts are stale)."""
    r = LLM.get(u["unit_id"])
    return r if r and r.get("attempts", 0) == u.get("attempts", 0) else None


def llm_values(u: dict) -> dict:
    """(table, record, field) -> value proposed by the LLM (conversions + count decisions)."""
    r = llm_for(u) or {}
    return {(c.get("table"), c.get("record"), c.get("field")): c.get("to")
            for c in (r.get("conversions") or []) + (r.get("count_decisions") or []) if c.get("field") != "__delete__"}

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


_MISSING = object()


def cell_value(u: dict, c: dict):
    """Current draft value of a (table, record, field) reference, or _MISSING if it does not exist."""
    try:
        t, r = u["draft"][c.get("table")], c.get("record")
        row = t if r is None else t[int(r)]
        return row[c.get("field")] if c.get("field") in row else _MISSING
    except (KeyError, IndexError, TypeError, ValueError):
        return _MISSING


def correction_widget(u: dict, table: str, rec: int | None, fld: str, proposed=None, short: bool = False):
    row = u["draft"][table] if rec is None else u["draft"][table][rec]
    ctx = {cfg.parent: u["draft"][cfg.parent], table: row}
    key = f"fix_{u['unit_id']}_{u.get('attempts', 0)}_{table}_{rec}_{fld}"
    label = fld if short else f"{table}.{fld}" + (f" [record {rec}]" if rec is not None else "")
    hint = f"current: {row.get(fld)!r}"
    if proposed is not None:
        label += " (LLM)"
    found = allowed_for(table, fld, ctx)
    if found is None:
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
        head = st.columns([5, 2, 2, 1.4] if related else [9, 1.4])
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
                with st.spinner("Re-running (and LLM review if it halts again)..."):
                    new = generator.rerun_in_file(choice, u["unit_id"], payload, cfg, deletions=deletions)
                st.toast(f"Unit {u['unit_id']}: {new['status']}")
                st.rerun()
with st.expander("Completed units"):
    for u in by_status("completed"):
        st.markdown(f"**Unit {u['unit_id']} - {u['key']}**")
        for table, data in u["draft"].items():
            st.dataframe(show(data), width="stretch")
