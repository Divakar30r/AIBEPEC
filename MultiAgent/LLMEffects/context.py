"""Builds the one-time context (rules, count rules, field descriptions) and the units payload."""
from __future__ import annotations

import json
from typing import Any

from masking import withhold_draft
from settings import Settings


def compact_rules(cfg: Settings, levels: list[list[str]]) -> dict[str, Any]:
    reg = json.loads(cfg.registry_dump.read_text(encoding="utf-8"))
    level_of = {f: i for i, lv in enumerate(levels) for f in lv}
    return {f: {"level": level_of.get(f), "depends_on": r["depends_on"],
                "branches": [{"guards": b["guards"], "constraint": b["constraint"], "allowed": b["allowed"]}
                             for b in r["branches"]]}
            for f, r in reg["rules"].items()}


def compact_counts(cfg: Settings) -> list[dict[str, Any]]:
    if not cfg.count_dump.exists():
        return []
    dump = json.loads(cfg.count_dump.read_text(encoding="utf-8"))
    return [{"target": r["target"], "value": r["value"], "counts_records_of": r["counts_records_of"],
             "combinations": [{"when": c["when"], "count": [c["count"]["min"], c["count"]["max"]]}
                              for c in r["combinations"]]} for r in dump["rules"]]


def unit_payload(units: list[dict[str, Any]], cfg: Settings) -> dict[str, Any]:
    """Drafts (populated fields only, masked fields withheld) + their violations, keyed by unit_id."""
    return {str(u["unit_id"]): {"draft": withhold_draft(u["draft"], cfg.mask_fields),
                                "violations": u["violations"],
                                "halted_before_level": u["halted_before_level"]} for u in units}


def dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)
