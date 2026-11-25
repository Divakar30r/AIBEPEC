"""Multi-agent supervisor (LangGraph) over the DataGenerator pipeline.

Agents / roles
  generate     Agent 1 - DataGenerator: rule-based generation (a tool-like worker, no LLM)
  repair       planning agent (B): swaps whole related-table sets between halted units, no LLM
  llm          Agent 2 - LLMEffects review: A) conversions applied level by level
  await_human  Agent 3 - human-in-the-loop: corrections in the UI (and LLMfeedback.json weights = shared memory)
  audit        auditor (A): at the END of a round (all units completed) reports which author broke a rule;
               report only, nothing is changed
The supervisor itself routes by plain rules and makes no LLM call. The run file is the persistent state.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "DataGenerator", ROOT):  # DataGenerator modules are imported by name (generator, settings, ...)
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
