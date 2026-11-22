"""Field type inference with frictionless (per row block, all columns at once).

frictionless gives one type per field (integer, number, boolean, date, datetime, year, string ...).
A type wins only if at least `field_confidence` of the non-missing values parse as it; we set that
to 1 - MIX_THRESHOLD, so a 'string' result on a mostly-numeric column means "mixed encodings".
Null-like tokens are passed as frictionless missing values (case variants included).
Returns {} when PROFILER=builtin or frictionless fails, so callers fall back to their own inference.
"""
from __future__ import annotations

import pandas as pd

from config import Settings, settings


def _missing_values(cfg: Settings) -> list[str]:
    out = {""}
    for t in cfg.null_tokens:
        out |= {t, t.lower(), t.upper(), t.title()}
    return sorted(out)


def infer_types(block: pd.DataFrame, cfg: Settings = settings) -> dict[str, str]:
    if cfg.profiler != "frictionless" or block.empty:
        return {}
    try:
        from frictionless import Detector, Resource

        data = [list(map(str, block.columns))] + block.fillna("").astype(str).map(str.strip).values.tolist()
        detector = Detector(sample_size=len(block), field_confidence=1 - cfg.mix_threshold,
                            field_missing_values=_missing_values(cfg))
        res = Resource(data=data, detector=detector)
        res.infer()
        return {f.name: f.type for f in res.schema.fields}
    except Exception:  # profiling must never break chunking
        return {}
