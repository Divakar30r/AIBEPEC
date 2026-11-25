# Multi-agent supervisor for DataGenerator (LangGraph)

## Context
The user wants to try multi-agent concepts on the existing pipeline:
- **Agent 1, DataGenerator:** rule-based generation, no LLM.
- **Agent 2, LLMEffects review:** LLM A) conversions and B) count decisions.
- **Agent 3, the human:** corrections in the UI, which become weighted pairs in `LLMEffects/LLMfeedback.json`.

A supervisor should coordinate them and add two capabilities:
- **(A) Audit:** say whether the LLM or the human broke a rule. Findings appear in a separate UI panel, and nothing is changed automatically.
- **(B) Repair:** before any LLM call, fix halted units by **swapping whole related-table sets** (all PolStakes of a unit) between halted units of the same run, re-keyed to their new parent. **Completed units are never touched.** This avoids Agent 2 calls where a pure rearrangement satisfies the rules.

Framing agreed in chat:
- A component without an LLM can be an agent if it perceives state, decides and acts.
- The Repair node (B) is the planning agent.
- The Generator is closer to a tool or worker.
- The human is a human-in-the-loop approver, and `LLMfeedback.json` is shared memory.
- The supervisor routes by rules and makes **no LLM call**.

## Design
New package `MultiAgent/Supervisor/`. It's a package, to avoid clashing with module names such as `settings`, `schema` and `config` in other folders.

### Graph (`Supervisor/graph.py`, LangGraph `StateGraph`)
- **The run file is the persistent state.** Each invocation rebuilds the graph state from the run JSON. There's no checkpointer, so Streamlit reruns can't lose it.
- **State fields:** `run_path`, `trigger` (`start | human`), `round`, `trace` (node visits), `done_nodes` (per round), `status`.
- **Nodes:**
  1. `generate` (Agent 1) calls `generator.run(load_config(..., llm_review=False))`. That flag already exists in `DataGenerator/settings.py`. Turning it off stops `run()` doing its own LLM auto-apply, so the supervisor decides when the LLM runs.
  2. `repair` (B) is described below.
  3. `llm` (Agent 2) calls the existing `generator.llm_review(path, ids)` and `generator.apply_llm_conversions(path, ids, cfg)`, which already use `_llm_cycle`, on units that are still halted.
  4. `await_human` (Agent 3) ends the graph with `status="awaiting_human"`. The existing UI correction flow is the human step. Afterwards the UI re-invokes the graph with `trigger="human"`.
  5. `audit` (A) is described below.

- **Supervisor router** (a conditional edge with plain rules):
  - no run file → `generate`
  - halted units and repair not yet run this round → `repair`
  - still halted, LLM enabled and not yet run this round → `llm`
  - still halted → `await_human` (END, the round waits for UI feedback)
  - **all units completed (the round is over, human feedback done) and changes not yet audited → `audit`**
  - otherwise → END (`done`)
  - After `trigger="human"`, the next pass is `repair → llm → (await_human | audit → END)`.
  - Audit runs only at the end of a round, once every unit is completed, never mid-round.
- **Trace:** the graph writes `run["supervisor"] = {rounds, trace:[{round,node,summary,at}], status}` into the run file.
- **Entry points:** `start(cfg_overrides)` and `resume(run_path, trigger="human")`, plus a CLI: `uv run python -m Supervisor.graph [--units N] [--seed S]`.

### (B) Repair agent (`Supervisor/repair.py`), no LLM
- **Candidates:** `needs_review` units only. Group them by `halted_before_level`, because only same-level units are comparable.
- **Feasibility:** child set j fits unit i if the trial draft `{parent_i, children_j re-keyed to key_i}` has no violations from the existing `generator.check_all(registry, cfg, plan, trial, levels_done=L)`. That covers field rules and count rules (`count_rules.check_counts`).
- **Assignment:** use maximum bipartite matching (Kuhn's algorithm) between units and child sets within the group, keeping each unit's own set as an option. This maximises the number of units that become valid.
- **Tie-break:** prefer sets that agree with positive count pairs in `LLMfeedback.json`, through `DataGenerator/weights.py`. That is the "based on UI feedback" part.
- **Apply:** a new `generator.swap_child_sets(run_path, {unit_id: donor_unit_id}, cfg)`:
  - rewrites each unit's child lists and key field
  - records `repair_applied:[{from_unit, to_unit, table, records}]` for provenance
  - resumes each changed unit from its halted level through `rerun_unit`, with no fixes and no LLM
- **Logging:** units that can't be fixed are left for `llm`. Each swap is written to the trace.

### (A) Audit agent (`Supervisor/audit.py`), report only
For every completed or halted unit, it re-checks each authored change against the unit's **current** draft:
- **Authored changes checked:** `llm_applied` (LLM), `user_applied` (Human) and `repair_applied` (Repair).
- **Checks:**
  - field rules, using `registry.validate_row` and the shared `same()` case-insensitive match from `DAGRegistry/load_rules.py`
  - count rules, using `check_counts`
  - `-1` ("never") pairs in `LLMfeedback.json`
  - human `override` values that bypassed rule options
- **Output:** `run["audit"] = [{unit_id, author, table, record, field, from, to, check, verdict, detail}]`. Every check is recorded, including passes, so the panel can show counts per author. Nothing is reverted.

### UI (`DataGenerator/app.py`)
- **Execute** calls `Supervisor.graph.start(...)` instead of `generator.run`.
- **"Apply changes & re-run"** keeps `generator.rerun_in_file(..., llm=False)`, then calls `Supervisor.graph.resume(path, "human")`.
- **New "Supervisor" panel** (its own expander or tab), with two sections:
  - **Agent trace:** round → node → summary, for example "repair: 3 units fixed by swapping child sets (u2←u5, u5←u2, u7←u9)" or "llm: 4 units".
  - **Audit findings:** grouped by author (LLM / Human / Repair), with violations highlighted. It's read-only.

## Files
- New: `Supervisor/__init__.py`, `graph.py`, `repair.py`, `audit.py`, `requirements.txt` (`langgraph>=1.2`).
  - A dry run showed `langgraph 1.2.24` installs without touching pandas 3.1.1 or numpy.
- Changed: `DataGenerator/generator.py`, adding `swap_child_sets()`. It reuses `rerun_unit`, `check_all`, `_rerun_once` patterns and the provenance lists.
- Changed: `DataGenerator/app.py` (Execute, resume after human, Supervisor panel).
- Unchanged: LLMEffects, which is still invoked through `generator.llm_review` as a subprocess. Also unchanged: DAGRegistry, DBHandler and XternalLoad.

## Verification
1. **Offline, LLM off:** `uv run python -m Supervisor.graph --units 10 --seed 7` with `llm_review` disabled.
   - The trace shows generate → repair → audit → await_human.
   - Check that repair reduced halted units where same-level child sets fit another parent.
   - Re-validate the swapped units with `check_all` and expect no violations.
   - Completed units must be unchanged; compare drafts before and after.
2. **Audit:** inject a rule-breaking `user_applied` entry and an `llm_applied` entry into a copy of a run file, run `audit`, and expect violations attributed to Human and LLM respectively. A clean change must yield a pass.
3. **UI:** `streamlit.testing` AppTest. The Supervisor panel renders the trace and findings, and Execute and re-run route through the graph without exceptions.
4. **With the LLM:** one real run. The LLM is called only for units that repair couldn't fix (check the trace counts and LLMEffects logs).



_Feature: Only Possiblity - Prediction not Enforcement_
I added 'Only Possibility' to the LLM feedback tables and to the generator. An in-memory test gives the 50% split from your example, and the app renders with no errors. Your LLMfeedback.json wasn't touched: its last change was your own Save at 15:38, before these tests. Reload the page at localhost:8501 to see the new table.

UI (DataGenerator/app.py)
- Count-based table: "Remove" is now Options, a dropdown with Remove and Only Possibility.
  - Pick Only Possibility and press Save, and the pair keeps the option ("Option": "Only Possibility" in the file). Clear the cell and Save to switch it off.
  - New runs keep the option when they merge into the feedback file.
- New "Predicted share" column: on Only Possibility rows it shows, for example, 0.50 (2 value pairs).
- Value-based table: its Options dropdown has only Remove, because Only Possibility only makes sense for a count pair.

Generation, Agent 1 (DataGenerator/weights.py)
- Share: the generator adds up the positive weights of the value pairs whose LLM value is the pair's parent value, capped at 1. Matching ignores case, and -1 pairs are left out.
  - From your example: senior_citizen→CI 0.3 + individual→CI 0.2 = 0.5.
- What it changes: that share of CI units get exactly Count INS records. Extra INS records are re-picked from the rule's other allowed values, and missing ones are added. The other units are left to the normal rules.
- Test (in memory, 4,000 CI units, alongside a normal "CI/INS x2" pair at weight 1):
  - 51% ended with exactly 1 INS and 49% with 2.
  - Units with another PolicyType were untouched.
- Precedence: Only Possibility pairs act before the weighted count pairs. Once one applies to a unit, no other pair can change that value's count.
- The repair agent now also uses these pairs, at their predicted share, as a tie-break.

Things to know
- The Only Possibility row's own Weightage is ignored. The share comes only from the value pairs.
- No value pair into the parent value means a share of 0, so the pair does nothing. This happens, for example, when CI only ever comes from the rules and never from a conversion. The Predicted share column shows 0 in that case.
- It's a prediction, not a hard rule. If a unit still has extra INS records and the rules allow no other value for them, the unit halts as before.