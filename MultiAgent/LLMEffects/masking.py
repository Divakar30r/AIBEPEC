"""Replace configured fields (fully qualified Table.Field) with tokens before anything leaves the machine."""
from __future__ import annotations

import copy
from typing import Any


def mask_draft(draft: dict[str, Any], mask_fields: tuple[str, ...]) -> dict[str, Any]:
    out = copy.deepcopy(draft)
    n = 0
    for table, data in out.items():
        for rec in [data] if isinstance(data, dict) else data:
            for fld in list(rec):
                if f"{table}.{fld}" in mask_fields and rec[fld] not in (None, ""):
                    n += 1
                    rec[fld] = f"<MASKED:{n}>"
    return out
