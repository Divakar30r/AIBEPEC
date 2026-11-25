"""API tests on a temporary runs folder and a temporary LLMfeedback.json - real run files and the real feedback
list are never touched. Needs the data DB (relations from FKs), like the generator itself. No LLM calls.

    uv run python -m pytest ReviewUI/backend/test_api.py -q        (from MultiAgent/)
"""
from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="reviewui_"))
os.environ["REVIEWUI_RUNS_DIR"] = str(TMP)
os.environ["LLMFEEDBACK_PATH"] = str(TMP / "LLMfeedback.json")

from fastapi.testclient import TestClient  # noqa: E402

import ReviewUI.backend.main as api  # noqa: E402
import generator  # noqa: E402
import review_logic  # noqa: E402
from settings import load_config  # noqa: E402

api.LLM = False
client = TestClient(api.app)


@pytest.fixture(scope="module")
def run_id() -> str:
    """A fresh run (LLM off) in the temp folder, with at least one halted unit."""
    for seed in (7, 11, 23, 31, 47):
        cfg = load_config(units=8, seed=seed, llm_review=False, per_key={"PolStakes": (1, 3)})
        path = generator.run(dataclasses.replace(cfg, output_dir=TMP))
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if any(u["status"] == "needs_review" for u in data["units"]):
            return data["run_id"]
    pytest.skip("no halted unit generated")


def test_config():
    c = client.get("/api/config").json()
    assert c["parent"] and c["children"] and c["levels"]
    assert c["options"] == {"only": "Only Possibility", "max": "Max Possibility"}


def test_runs_and_edit_plan(run_id):
    assert any(r["run_id"] == run_id for r in client.get("/api/runs").json())
    d = client.get(f"/api/runs/{run_id}").json()
    cfg = load_config()
    rules = review_logic.rules_dump(cfg)
    halted = [u for u in d["units"] if u["status"] == "needs_review"]
    assert halted and all(u["edit"] is not None for u in halted)
    checked = 0
    for u in halted:
        for c in u["edit"]["cells"]:
            if c["spec"]["editor"] != "select":
                continue
            row = u["draft"][c["table"]] if c["record"] is None else u["draft"][c["table"]][c["record"]]
            kind, spec, _ = review_logic.allowed_for(rules, c["table"], c["field"],
                                                     {cfg.parent: u["draft"][cfg.parent], c["table"]: row})
            assert c["spec"]["options"] == list(spec)  # in-cell dropdown = that row's rule options
            checked += 1
    assert all(u["edit"] is None for u in d["units"] if u["status"] == "completed")
    print(f"{checked} select cell(s) checked")


def test_feedback_roundtrip_keeps_option_and_order():
    rows = [{"RelatedTable": "PolStakes", "RelatedField": "PolStakes.StakerCodes.Unique", "RelatedFieldValue": v,
             "Field": "PolMaster.PolicyType", "value": "CI", "Count": 1, "Weightage": w, "_ui": "x", **extra}
            for v, w, extra in (("SPS", 0.3, {"Option": "Max Possibility"}), ("INS", 0.0, {"Option": "Only Possibility"}),
                                ("AGT", 0.5, {"Option": ""}))]
    assert client.put("/api/feedback", json={"Value-based": [], "Count-based": rows}).json()["Count-based"] == 3
    got = client.get("/api/feedback").json()["Count-based"]
    assert [r["RelatedFieldValue"] for r in got] == ["SPS", "INS", "AGT"]
    assert [r.get("Option") for r in got] == ["Max Possibility", "Only Possibility", None]
    assert all("_ui" not in r for r in got)


def test_rerun_on_copy(run_id):
    d = client.get(f"/api/runs/{run_id}").json()
    u = next(u for u in d["units"] if u["status"] == "needs_review")
    cell = next((c for c in u["edit"]["cells"] if c["spec"]["editor"] == "select" and c["spec"]["options"]), None)
    dels = {t: rs for t, rs in u["edit"]["delete"].items() if rs}
    if cell is None and not dels:
        pytest.skip("no select cell or deletion to apply")
    fixes = [] if cell is None else [{"table": cell["table"], "record": cell["record"], "field": cell["field"],
                                      "value": cell["spec"]["options"][0]}]
    r = client.post(f"/api/runs/{run_id}/units/{u['unit_id']}/rerun", json={"fixes": fixes, "deletions": dels})
    assert r.status_code == 200, r.text
    after = json.loads((TMP / f"run_{run_id}.json").read_text(encoding="utf-8"))
    nu = next(x for x in after["units"] if x["unit_id"] == u["unit_id"])
    assert nu.get("attempts", 0) == u.get("attempts", 0) + 1
    assert (after.get("supervisor") or {}).get("trace")  # supervisor pass ran after the human step
    assert r.json()["status"] == nu["status"]


def test_rerun_nothing_is_400(run_id):
    d = client.get(f"/api/runs/{run_id}").json()
    u = next((u for u in d["units"] if u["status"] == "needs_review"), d["units"][0])
    assert client.post(f"/api/runs/{run_id}/units/{u['unit_id']}/rerun", json={}).status_code == 400


def test_value_pair_archive_kept_and_still_applied():
    vals = [{"Table": "PolMaster", "Field": "PolicyType", "Type": "text", "current_value": c, "LLM_value": "CI",
             "Weightage": 1.0, **({"Option": "Archive"} if c == "senior_citizen" else {})}
            for c in ("individual", "senior_citizen")]
    client.put("/api/feedback", json={"Value-based": vals, "Count-based": []})
    got = client.get("/api/feedback").json()["Value-based"]
    assert [r["current_value"] for r in got] == ["individual", "senior_citizen"]  # priority order kept
    assert [r.get("Option") for r in got] == [None, "Archive"]
    import random
    import weights
    w = weights.load_weights()  # archived pairs still apply in generation
    assert w.remap("PolMaster", "PolicyType", "senior_citizen", random.Random(1))[0] == "CI"


def test_field_options_follow_dependencies():
    """A list field gets a dropdown only when all fields it depends on have values; the options are the rule's
    branch for those values (unsaved edits are just values in the request)."""
    rules = review_logic.rules_dump(load_config())
    lang = rules["PolMaster.Language"]  # depends on PolMaster.JurisdictionState
    dep = lang["depends_on"][0]
    branch = next(b for b in lang["branches"] if b["guards"])
    state = branch["guards"][dep]
    body = {"table": "PolMaster", "fields": ["Language", "PolicyType"], "values": {"PolMaster.PolicyType": "CI"}}
    r = client.post("/api/field-options", json=body).json()
    assert r["Language"]["options"] is None if "options" in r["Language"] else True
    assert r["Language"]["editor"] != "select" and r["Language"]["missing"] == [dep]
    assert r["PolicyType"]["editor"] == "select" and r["PolicyType"]["options"]  # no dependencies
    body["values"][dep] = state
    r = client.post("/api/field-options", json=body).json()
    assert r["Language"]["editor"] == "select" and r["Language"]["missing"] == []
    assert set(branch["allowed"]) <= set(r["Language"]["options"])


def test_rerun_keeps_edited_cells_of_later_levels():
    """A reviewer-set cell at a level the re-run (re)generates keeps its value."""
    import random
    from schema import build_plan
    cfg = load_config()
    plan, registry = build_plan(cfg), generator.load_rules()
    files = list(TMP.glob("run_*.json")) + sorted(Path(cfg.output_dir).glob("run_*.json"))  # real runs: read only
    done = next((u for p in files for u in json.loads(p.read_text(encoding="utf-8"))["units"]
                 if u["status"] == "completed"), None)
    if done is None:
        pytest.skip("no completed unit to start from")
    lvl1 = [f for t, f in plan.levels[1] if t == cfg.parent]
    assert lvl1, "need a parent field at level 1"
    unit = generator.Unit(done["unit_id"], done["key"], json.loads(json.dumps(done["draft"])), levels_done=1)
    unit.draft[cfg.parent][lvl1[0]] = "KEPT_BY_REVIEWER"
    rng = random.Random(5)
    out = generator._advance(unit, 1, cfg, plan, registry, [], rng, generator.Faker(), keep={(cfg.parent, None, lvl1[0])})
    assert out.draft[cfg.parent][lvl1[0]] == "KEPT_BY_REVIEWER"


def test_only_list_fields_enter_feedback():
    lists = set(client.get("/api/config").json()["list_fields"])
    assert "PolMaster.PolicyType" in lists and "PolStakes.StakerName" not in lists
    bad = {"Table": "PolStakes", "Field": "StakerName", "Type": "text", "current_value": "x", "LLM_value": "y", "Weightage": 1}
    assert client.post("/api/feedback/pair", json={"section": "Value-based", "row": bad}).status_code == 400
    ok = {"Table": "PolMaster", "Field": "PolicyType", "Type": "text", "current_value": "family", "LLM_value": "CI", "Weightage": 0.5}
    assert client.post("/api/feedback/pair", json={"section": "Value-based", "row": ok}).status_code == 200
    cnt = {"RelatedTable": "PolStakes", "RelatedField": "PolStakes.StakerAge", "RelatedFieldValue": "30",
           "Field": "PolMaster.PolicyType", "value": "CI", "Count": 1, "Weightage": -0.5}  # StakerAge is a range
    assert client.post("/api/feedback/pair", json={"section": "Count-based", "row": cnt}).status_code == 400
    fb = weights_module().load_feedback()
    assert all(f"{r['Table']}.{r['Field']}" in lists for r in fb["Value-based"])


def weights_module():
    import weights
    return weights
