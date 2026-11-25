"""Keep configured fields (fully qualified Table.Field, config.json "mask_fields") from ever leaving the machine."""
from __future__ import annotations

import copy
from typing import Any


def withhold_draft(draft: dict[str, Any], mask_fields: tuple[str, ...]) -> dict[str, Any]:
    """Copy of the draft WITHOUT the masked fields. They are dropped rather than replaced by a token: a token
    cannot help any check and only costs prompt tokens. Record order (indices) is unchanged."""
    out = copy.deepcopy(draft)
    for table, data in out.items():
        for rec in [data] if isinstance(data, dict) else data:
            for fld in [f for f in rec if f"{table}.{f}" in mask_fields]:
                del rec[fld]
    return out
