"""Generic column-wise chunker for CSV schema discovery.

Nothing here knows the file: every column is profiled purely from its values.
The CSV is split into row blocks of `row_chunk_size` rows; inside each block every column
becomes one chunk - a compact text profile covering:

  * nulls      - empty cells and null-like tokens (NULL_TOKENS), which tokens were seen
  * types      - share of values per detected kind (integer, decimal, formatted number,
                 boolean, date, datetime, email, url, phone, uuid, masked, text), so mixed
                 encodings show up instead of being hidden by a single label
  * ranges     - numeric min/max (formatted numbers included), date min/max, text length
  * encoding   - value shapes, date formats used, case variants of the same value,
                 surrounding whitespace, leading zeros, currency/percent/unit decorations
  * cardinality- distinct count, all-unique (likely identifier), top values when low

Raw values are only included when safe: columns listed in REDACT_COLUMNS, or detected as
emails / phones / masked identifiers, are described by shape only.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

import profiler
from config import Settings, settings

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%Y%m%d",
                "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%d.%m.%Y")
DATETIME_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                    "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M")
BOOL_SETS = ({"true", "false"}, {"yes", "no"}, {"y", "n"}, {"t", "f"}, {"0", "1"})

_INT = re.compile(r"^[+-]?\d+$")
_DEC = re.compile(r"^[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?$")
# number with decorations: currency symbol, thousands separators, %, or a trailing unit word
_FMT_NUM = re.compile(r"^(?P<pre>[^\w\s+-]{1,3})?\s*(?P<num>[+-]?\d{1,3}(,\d{2,3})+(\.\d+)?|[+-]?\d+(\.\d+)?)"
                      r"\s*(?P<post>%|[A-Za-z]{1,5})?$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_URL = re.compile(r"^(https?|ftp)://\S+$", re.I)
_PHONE = re.compile(r"^\+?[\d\s().-]{7,}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_MASKED = re.compile(r"[X*#]{3,}", re.I)
SENSITIVE_KINDS = {"email", "phone", "masked"}


@dataclass(frozen=True)
class ColumnChunk:
    source: str
    column_name: str
    chunk_idx: int
    row_start: int  # 1-based, inclusive
    row_end: int
    content: str


# --------------------------------------------------------------------------- #
# Value-level detection
# --------------------------------------------------------------------------- #
def shape(value: str) -> str:
    """'AB12-x' -> 'AA99-a'; runs of 4+ collapsed: 'A{6}'."""
    s = "".join("A" if c.isupper() else "a" if c.isalpha() else "9" if c.isdigit() else c for c in value)
    return re.sub(r"(.)\1{3,}", lambda m: f"{m.group(1)}{{{len(m.group(0))}}}", s)


def _date_format(v: str, formats: tuple[str, ...]) -> str | None:
    for f in formats:
        try:
            datetime.strptime(v, f)
            return f
        except ValueError:
            continue
    return None


def classify(v: str) -> tuple[str, float | datetime | None, str | None]:
    """(kind, parsed value, detail). detail = date format or number decoration."""
    if _INT.match(v):
        return "integer", float(v), "leading_zero" if len(v.lstrip("+-")) > 1 and v.lstrip("+-")[0] == "0" else None
    if _DEC.match(v):
        return "decimal", float(v), None
    if f := _date_format(v, DATETIME_FORMATS):
        return "datetime", datetime.strptime(v, f), f
    if f := _date_format(v, DATE_FORMATS):
        return "date", datetime.strptime(v, f), f
    if _UUID.match(v):
        return "uuid", None, None
    if _EMAIL.match(v):
        return "email", None, None
    if _URL.match(v):
        return "url", None, None
    m = _FMT_NUM.match(v)
    if m and (m.group("pre") or m.group("post") or "," in m.group("num")):
        deco = []
        pre, post = m.group("pre"), m.group("post")
        if pre:
            deco.append("currency_prefix" if all(unicodedata.category(c) == "Sc" for c in pre) else f"prefix:{pre}")
        if "," in m.group("num"):
            deco.append("thousands_sep")
        if post:
            deco.append("percent" if post == "%" else f"unit_suffix:{post}")
        return "formatted_number", float(m.group("num").replace(",", "")), "+".join(deco)
    if _PHONE.match(v) and sum(c.isdigit() for c in v) >= 7:
        return "phone", None, None
    if _MASKED.search(v):
        return "masked", None, None
    return "text", None, None


def _is_null(raw: object, tokens: frozenset[str]) -> bool:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return True
    s = str(raw).strip().lower()
    return s == "" or s in tokens


def _dominant(kinds: Counter, n: int) -> tuple[str, float]:
    """Dominant kind and its share; integers inside a decimal column count as decimal."""
    main, cnt = kinds.most_common(1)[0]
    if main in ("integer", "decimal") and kinds["integer"] and kinds["decimal"]:
        main, cnt = "decimal", kinds["integer"] + kinds["decimal"]
    return main, cnt / n


def refine_mixed(vals: list[tuple[int, str]], cfg: Settings) -> tuple[list[str], int, bool]:
    """Re-chunk a mixed column into smaller row blocks (halving each round) to locate the
    off-type values. Returns (region descriptions of the last round, rounds used, localised).
    Stops early once the dirty sub-blocks are <= 25% of all sub-blocks (values are localised)."""
    regions: list[str] = []
    for r in range(1, max(1, cfg.mix_max_rounds) + 1):
        size = max(1, math.ceil(len(vals) / 2 ** r))
        subs = [vals[i:i + size] for i in range(0, len(vals), size)]
        regions, dirty = [], 0
        for s in subs:
            k = Counter(classify(v)[0] for _, v in s)
            _, share = _dominant(k, len(s))
            if 1 - share >= cfg.mix_threshold:
                dirty += 1
                mix = " ".join(f"{kk} {c / len(s):.0%}" for kk, c in k.most_common(3))
                regions.append(f"rows {s[0][0]}-{s[-1][0]} {mix}")
        if dirty <= 0.25 * len(subs):
            return regions, r, True
    return regions, max(1, cfg.mix_max_rounds), False


# --------------------------------------------------------------------------- #
# Column profile
# --------------------------------------------------------------------------- #
def profile_column(name: str, series: pd.Series, cfg: Settings = settings, row_offset: int = 1,
                   fl_type: str | None = None) -> str:
    """row_offset: file row number of the series' first value; fl_type: frictionless field type."""
    tokens = frozenset(t.lower() for t in cfg.null_tokens)
    raw = [None if pd.isna(x) else str(x) for x in series]
    rows = [row_offset + i for i, r in enumerate(raw) if not _is_null(r, tokens)]
    total = len(raw)
    null_seen = Counter((r.strip() or "<empty>") if r is not None else "<empty>" for r in raw if _is_null(r, tokens))
    values = [r for r in raw if not _is_null(r, tokens)]
    stripped = [v.strip() for v in values]
    n = len(stripped)

    lines = [f"column: {name}", f"non_null: {n}/{total} (null_rate {(total - n) / total:.0%})" if total else "non_null: 0/0"]
    if null_seen:
        lines.append("null_tokens_seen: " + ", ".join(f"{t!r} x{c}" for t, c in null_seen.most_common(4)))
    if not n:
        lines.append("inferred_type: empty")
        return "\n".join(lines)

    kinds, parsed, details = Counter(), {}, Counter()
    for v in stripped:
        k, p, d = classify(v)
        kinds[k] += 1
        if p is not None:
            parsed.setdefault(k, []).append(p)
        if d:
            details[f"{k}:{d}"] += 1

    lower = {v.lower() for v in stripped}
    if len(lower) <= 2 and any(lower <= s for s in BOOL_SETS):
        main = "boolean"
    else:
        main, share = _dominant(kinds, n)
        if 1 - share >= cfg.mix_threshold:
            regions, rounds, localised = refine_mixed(list(zip(rows, stripped)), cfg)
            lines.append(f"resolved_type: {main} (max share {share:.0%}; mixed after {rounds} re-chunk round(s), "
                         f"off-type values {'localised' if localised else 'scattered'})")
            if regions:
                lines.append("mixed_regions: " + "; ".join(regions[:4]) + (" ..." if len(regions) > 4 else ""))
            main = f"mixed ({main} dominant)"
    distinct = len(set(stripped))
    if main == "text" and distinct <= max(20, 0.05 * n):
        main = "categorical"
    lines.append(f"inferred_type: {main}")
    if fl_type:
        lines.append(f"frictionless_type: {fl_type} (confidence {1 - cfg.mix_threshold:.0%})")
    lines.append("type_mix: " + ", ".join(f"{k} {c / n:.0%}" for k, c in kinds.most_common()))
    lines.append(f"distinct: {distinct}" + (" (all unique - likely identifier)" if distinct == n and n > 1
                                          and main in ("text", "integer", "uuid", "masked") else ""))

    # ranges
    nums = parsed.get("integer", []) + parsed.get("decimal", []) + parsed.get("formatted_number", [])
    if nums:
        lines.append(f"numeric_range: {min(nums):g} .. {max(nums):g}")
    dates = parsed.get("date", []) + parsed.get("datetime", [])
    if dates:
        lines.append(f"date_range: {min(dates):%Y-%m-%d} .. {max(dates):%Y-%m-%d}")
    lens = [len(v) for v in stripped]
    lines.append(f"length_range: {min(lens)} .. {max(lens)}")

    # encoding patterns
    lines.append("value_shapes: " + ", ".join(f"{s} x{c}" for s, c in
                                               Counter(shape(v) for v in stripped).most_common(3)))
    if details:
        lines.append("encodings: " + ", ".join(f"{d} x{c}" for d, c in details.most_common(6)))
    case_groups = Counter(v.lower() for v in set(stripped))
    variants = sorted({v for v in set(stripped) if case_groups[v.lower()] > 1}, key=str.lower)
    if variants:
        lines.append(f"case_variants: {len([k for k, c in case_groups.items() if c > 1])} value(s) spelled "
                     f"with different case, e.g. {variants[:4]}")
    ws = sum(v != s for v, s in zip(values, stripped))
    if ws:
        lines.append(f"surrounding_whitespace: {ws} value(s)")

    # values - only when safe
    sensitive = name in cfg.redact_columns or any(kinds[k] / n >= 0.5 for k in SENSITIVE_KINDS)
    if sensitive:
        lines.append("values: <redacted - shapes only>")
    elif distinct <= 25:
        top = Counter(stripped).most_common(cfg.sample_values)
        lines.append("top_values: " + ", ".join(f"{v} ({c})" for v, c in top))
    else:
        dominant = {"integer", "decimal"} if main.startswith(("decimal", "mixed (decimal", "integer", "mixed (integer"))             else {kinds.most_common(1)[0][0]}
        minority = [v for v in stripped if classify(v)[0] not in dominant]
        examples = list(dict.fromkeys(stripped))[:cfg.sample_values]
        lines.append("examples: " + ", ".join(examples))
        if minority:
            lines.append("off_type_examples: " + ", ".join(list(dict.fromkeys(minority))[:4]))
    return "\n".join(lines)


def read_csv(path: Path, cfg: Settings) -> pd.DataFrame:
    """Everything as text (no pandas type guessing); utf-8 first, then a lenient fallback."""
    kw = dict(dtype=str, keep_default_na=False, nrows=cfg.max_rows or None)
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def chunk_csv(path: Path | str | None = None, cfg: Settings = settings) -> list[ColumnChunk]:
    path = Path(path or cfg.csv_path or "")
    if not path.is_file():
        raise FileNotFoundError(f"CSV not found: {path!s} - set CSV_PATH in .env")
    df = read_csv(path, cfg)
    size = max(1, cfg.row_chunk_size)
    chunks: list[ColumnChunk] = []
    for idx, start in enumerate(range(0, len(df), size)):
        block = df.iloc[start:start + size]
        fl = profiler.infer_types(block, cfg)
        for col in df.columns:
            text = (f"source: {path.name}\nrows: {start + 1}-{start + len(block)}\n"
                    + profile_column(col, block[col], cfg, row_offset=start + 1, fl_type=fl.get(str(col))))
            chunks.append(ColumnChunk(path.name, col, idx, start + 1, start + len(block), text))
    return chunks


if __name__ == "__main__":
    cs = chunk_csv()
    print(f"{len(cs)} chunks, {len({c.column_name for c in cs})} columns, {len({c.chunk_idx for c in cs})} row blocks")
    for c in [c for c in cs if c.chunk_idx == 0][:5]:
        print("-" * 60 + "\n" + c.content)
