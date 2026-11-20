"""Column-wise chunker for CSV schema discovery.

The CSV is split into row blocks of `row_chunk_size` rows. Inside each block every
column becomes its own chunk: a compact text profile (inferred type, null rate, value
shapes, top values, numeric range). Profiles - not raw rows - are what we embed, because
the goal is to identify the schema, not to answer questions about individual records.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config import Settings, settings


@dataclass(frozen=True)
class ColumnChunk:
    source: str
    column_name: str
    chunk_idx: int
    row_start: int  # 1-based, inclusive
    row_end: int
    content: str


def _shape(value: str) -> str:
    """'IND103304' -> 'AAA999999', '2019-09-13' -> '9999-99-99' (runs collapsed to keep it short)."""
    s = re.sub(r"[A-Za-z]", "A", value)
    s = re.sub(r"\d", "9", s)
    return re.sub(r"(.)\1{3,}", lambda m: f"{m.group(1)}{{{len(m.group(0))}}}", s)


def _infer_type(values: pd.Series) -> str:
    if values.empty:
        return "empty"
    num = pd.to_numeric(values, errors="coerce")
    if num.notna().mean() >= 0.95:
        return "integer" if (num.dropna() % 1 == 0).all() else "decimal"
    iso = pd.to_datetime(values, format="%Y-%m-%d", errors="coerce")
    if iso.notna().mean() >= 0.95:
        return "date"
    if values.nunique() <= max(20, 0.05 * len(values)):
        return "categorical"
    return "text"


def profile_column(name: str, series: pd.Series, cfg: Settings) -> str:
    total = len(series)
    values = series.dropna().astype(str).str.strip()
    values = values[values != ""]
    non_null = len(values)
    dtype = _infer_type(values)
    lines = [
        f"column: {name}",
        f"inferred_type: {dtype}",
        f"non_null: {non_null}/{total} (null_rate {1 - non_null / total:.0%})" if total else "non_null: 0/0",
        f"distinct: {values.nunique()}",
    ]
    if non_null:
        shapes = values.map(_shape).value_counts().head(3)
        lines.append("value_shapes: " + ", ".join(f"{s} x{c}" for s, c in shapes.items()))
    if dtype in ("integer", "decimal"):
        num = pd.to_numeric(values, errors="coerce")
        lines.append(f"numeric_range: {num.min():g} .. {num.max():g}")
    elif non_null and pd.to_numeric(values, errors="coerce").notna().any():
        bad = values[pd.to_numeric(values, errors="coerce").isna()]
        if len(bad) and name not in cfg.redact_columns:
            lines.append(f"non_numeric_examples: {list(bad.head(3))}")
    if dtype == "date":
        d = pd.to_datetime(values, format="%Y-%m-%d", errors="coerce")
        lines.append(f"date_range: {d.min().date()} .. {d.max().date()}")
    if name in cfg.redact_columns:
        lines.append("values: <redacted - personal data; shapes only>")
    elif dtype in ("categorical", "integer") and values.nunique() <= 25:
        top = values.value_counts().head(cfg.sample_values)
        lines.append("top_values: " + ", ".join(f"{v} ({c})" for v, c in top.items()))
    elif non_null:
        lines.append("examples: " + ", ".join(values.drop_duplicates().head(cfg.sample_values).astype(str)))
    return "\n".join(lines)


def chunk_csv(path: Path | str | None = None, cfg: Settings = settings) -> list[ColumnChunk]:
    path = Path(path or cfg.csv_path)
    df = pd.read_csv(path, dtype=str, nrows=cfg.max_rows or None, encoding="utf-8-sig")
    size = max(1, cfg.row_chunk_size)
    chunks: list[ColumnChunk] = []
    for idx, start in enumerate(range(0, len(df), size)):
        block = df.iloc[start:start + size]
        for col in df.columns:
            text = f"source: {path.name}\nrows: {start + 1}-{start + len(block)}\n" + profile_column(col, block[col], cfg)
            chunks.append(ColumnChunk(path.name, col, idx, start + 1, start + len(block), text))
    return chunks


if __name__ == "__main__":
    cs = chunk_csv()
    print(f"{len(cs)} chunks, {len({c.column_name for c in cs})} columns, "
          f"{len({c.chunk_idx for c in cs})} row blocks")
    for c in cs[:3] + [x for x in cs if x.column_name in ("total_claim_amount", "customer_name")][:2]:
        print("-" * 60, f"\n{c.content}")
