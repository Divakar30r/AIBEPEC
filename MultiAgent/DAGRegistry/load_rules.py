"""Rule registry loader: parse -> normalize -> index -> link -> topo-sort -> compile -> freeze.

Runs once at startup (see load_rules.txt). Per-row cost is a dict lookup plus
a call to a pre-compiled closure. Source rules: ../PolRef.json.

Semantics (from load_rules.txt):
  * AllowedValues object  -> the only branch.
  * AllowedValues array   -> branches are OR-ed.
  * Inside a branch, guard predicates and the domain constraint are AND-ed.
  * A value is valid when at least one branch has all its guards true and the
    value satisfies that branch's domain constraint. If no branch applies the
    value is invalid ("no applicable branch").
"""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from format_tokens import DATE_FORMATS  # noqa: E402  (shared format vocabulary)

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "PolRef.json"

# Closed vocabulary: these keys are domain constraints, every other key is a guard.
DOMAIN_KEYS = frozenset({"ListStr", "RangeInt", "Range_YYYYMM", "Range_YYYYMMDD", "Range_C"})

Node = tuple[str, str]  # (table, field)
Row = Mapping[str, Mapping[str, Any]]  # {table: {field: value}}


class RuleError(ValueError):
    """Malformed rule file."""


class CycleError(RuleError):
    """Rule dependencies form a cycle (raised at load time)."""


# --------------------------------------------------------------------------- #
# Range_C mini-DSL:  <Table.Field><op>:<unit>:<magnitude>   e.g. PolMaster.SystemDate>:D:10
# --------------------------------------------------------------------------- #
_RANGE_C = re.compile(r"^(?P<ref>[A-Za-z_][\w.]*?)(?P<op>>=|<=|>|<|=):(?P<unit>[DWMY]):(?P<mag>\d+)$")


@dataclass(frozen=True)
class RangeCAst:
    ref: Node
    op: str
    unit: str
    magnitude: int


def parse_range_c(text: str, table: str, tables: frozenset[str] | None = None) -> RangeCAst:
    m = _RANGE_C.match(text.strip())
    if not m:
        raise RuleError(f"Bad Range_C expression: {text!r}")
    return RangeCAst(_to_node(m["ref"], table, tables), m["op"], m["unit"], int(m["mag"]))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _to_node(ref: str, default_table: str, tables: frozenset[str] | None = None) -> Node:
    """'PolMaster.PolicyType' -> (PolMaster, PolicyType); 'StakerCodes.Unique' stays in default table."""
    head, sep, tail = ref.partition(".")
    if sep and (head in tables if tables is not None else head[:1].isupper() and head.startswith("Pol")):
        return head, tail
    return default_table, ref


def _to_date(v: Any, allow_month: bool = True) -> dt.date:
    """Read a date written in any shared format token (../format_tokens.py): date / datetime objects,
    YYYY-MM-DD, YYYYMMDD, DD/MM/YYYY, ... ; 6-digit YYYYMM (-> first of month) only if allow_month.
    Rules use this to check BOUNDARIES - the value's format is never part of the rule."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    if re.fullmatch(r"\d{6}", s):
        if not allow_month:
            raise ValueError(f"month-only value {s!r} where a full date is required")
        return dt.date(int(s[:4]), int(s[4:]), 1)
    for pattern in DATE_FORMATS.values():
        if pattern == "%Y%m":
            continue
        try:
            return dt.datetime.strptime(s, pattern).date()
        except ValueError:
            continue
    return dt.date.fromisoformat(s)  # last resort (other ISO variants); raises ValueError


def _shift(d: dt.date, unit: str, n: int) -> dt.date:
    if unit == "D":
        return d + dt.timedelta(days=n)
    if unit == "W":
        return d + dt.timedelta(weeks=n)
    months = n if unit == "M" else 12 * n
    idx = d.year * 12 + (d.month - 1) + months
    y, m = divmod(idx, 12)
    return dt.date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


# --------------------------------------------------------------------------- #
# Compiled structures (all frozen)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Branch:
    guards: tuple[tuple[Node, Any], ...]
    constraint: str  # one of DOMAIN_KEYS
    spec: Any  # raw constraint value, e.g. the ListStr list
    refs: tuple[Node, ...]
    check: Callable[[Row, Any], bool]  # compiled: (ctx, value) -> bool


@dataclass(frozen=True)
class FieldRule:
    table: str
    field: str
    branches: tuple[Branch, ...]
    deps: frozenset[Node]

    def validate(self, ctx: Row, value: Any) -> bool:
        return any(b.check(ctx, value) for b in self.branches)


@dataclass(frozen=True)
class Violation:
    table: str
    field: str
    value: Any
    reason: str


@dataclass(frozen=True)
class Registry:
    version: str
    rules: Mapping[Node, FieldRule]  # O(1) index on (table, field)
    order: tuple[Node, ...]  # topological evaluation order
    graph: Mapping[Node, tuple[Node, ...]]  # adjacency list: dep -> dependents

    def rule(self, table: str, field: str) -> FieldRule | None:
        return self.rules.get((table, field))

    def validate_field(self, table: str, field: str, ctx: Row) -> bool:
        rule = self.rules.get((table, field))
        if rule is None:
            return True
        return rule.validate(ctx, ctx.get(table, {}).get(field))

    def validate_row(self, ctx: Row) -> list[Violation]:
        """Validate every ruled field present in ctx, in dependency order."""
        out: list[Violation] = []
        for node in self.order:
            rule = self.rules.get(node)
            table, field = node
            if rule is None or field not in ctx.get(table, {}):
                continue
            value = ctx[table][field]
            if not rule.validate(ctx, value):
                out.append(Violation(table, field, value, self._reason(rule, ctx)))
        return out

    @staticmethod
    def _reason(rule: FieldRule, ctx: Row) -> str:
        if not any(_guards_ok(b.guards, ctx) for b in rule.branches):
            return "no applicable branch for guard values"
        return "value outside allowed domain"


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def same(a: Any, b: Any) -> bool:
    """Value equality used by rules: strings compare case-insensitively ('active' == 'Active')."""
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    return a == b


def _guards_ok(guards: tuple[tuple[Node, Any], ...], ctx: Row) -> bool:
    for (t, f), expected in guards:
        if not same(ctx.get(t, {}).get(f), expected):
            return False
    return True


def _compile_check(constraint: str, spec: Any, table: str, tables: frozenset[str],
                   guards: tuple[tuple[Node, Any], ...]) -> tuple[Callable[[Row, Any], bool], tuple[Node, ...]]:
    refs: tuple[Node, ...] = ()
    if constraint == "ListStr":
        allowed = frozenset(spec)
        folded = frozenset(str(x).strip().casefold() for x in spec)  # case-insensitive list match
        dom: Callable[[Row, Any], bool] = lambda ctx, v: (v in allowed) or (
            isinstance(v, str) and v.strip().casefold() in folded)
    elif constraint == "RangeInt":
        lo, hi = spec
        dom = lambda ctx, v: _is_int(v) and lo <= int(v) <= hi
    elif constraint == "Range_YYYYMM":  # boundaries in YYYYMM; the value may be in any date format
        lo, hi = spec
        dom = lambda ctx, v: (m := _month_key(v)) is not None and lo <= m <= hi
    elif constraint == "Range_YYYYMMDD":  # boundaries in YYYYMMDD; the value may be in any date format
        lo, hi = spec
        dom = lambda ctx, v: (d := _day_key(v)) is not None and lo <= d <= hi
    elif constraint == "Range_C":
        ast = parse_range_c(spec, table, tables)
        refs = (ast.ref,)
        dom = lambda ctx, v: _range_c_ok(ast, ctx, v)
    else:  # pragma: no cover - guarded by caller
        raise RuleError(constraint)
    return (lambda ctx, v: _guards_ok(guards, ctx) and dom(ctx, v)), refs


def _is_int(v: Any) -> bool:
    try:
        int(v)
        return not isinstance(v, bool)
    except (TypeError, ValueError):
        return False


def _day_key(v: Any) -> int | None:
    """Any full date -> YYYYMMDD int for boundary checks; None if not a real date (e.g. 20230231, 202001)."""
    try:
        return int(_to_date(v, allow_month=False).strftime("%Y%m%d"))
    except (TypeError, ValueError):
        return None


def _month_key(v: Any) -> int | None:
    """Any date or YYYYMM -> YYYYMM int for boundary checks."""
    try:
        d = _to_date(v)
        return d.year * 100 + d.month
    except (TypeError, ValueError):
        return None


def _range_c_ok(ast: RangeCAst, ctx: Row, value: Any) -> bool:
    """'>'/'>=': value >= ref + n (at least n beyond). '<'/'<=': value <= ref - n. '=': value == ref + n."""
    t, f = ast.ref
    ref = ctx.get(t, {}).get(f)
    if ref is None or value is None:
        return False
    try:
        v, r = _to_date(value), _to_date(ref)
    except ValueError:
        return False
    if ast.op in (">", ">="):
        return v >= _shift(r, ast.unit, ast.magnitude)
    if ast.op in ("<", "<="):
        return v <= _shift(r, ast.unit, -ast.magnitude)
    return v == _shift(r, ast.unit, ast.magnitude)


def _kahn(nodes: set[Node], edges: dict[Node, set[Node]]) -> list[Node]:
    indeg = {n: 0 for n in nodes}
    for dsts in edges.values():
        for d in dsts:
            indeg[d] += 1
    ready = sorted(n for n, k in indeg.items() if k == 0)
    order: list[Node] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for d in sorted(edges.get(n, ())):
            indeg[d] -= 1
            if indeg[d] == 0:
                ready.append(d)
    if len(order) != len(nodes):
        stuck = sorted(n for n, k in indeg.items() if k > 0)
        raise CycleError(f"Rule dependency cycle among: {stuck}")
    return order


def build_registry(raw: list[dict[str, Any]], version: str = "dev") -> Registry:
    # 1/2. Deserialized input -> normalize into branches.
    tables = frozenset(r["Table"] for r in raw if "Table" in r)
    parsed: dict[Node, list[tuple[tuple[tuple[Node, Any], ...], str, Any]]] = {}
    for i, r in enumerate(raw):
        table = r.get("Table")
        field = r.get("Field", r.get("PolicyField"))  # first rule uses 'PolicyField'
        if not table or not field or "AllowedValues" not in r:
            raise RuleError(f"Rule #{i} needs Table, Field and AllowedValues: {r}")
        key = (table, field)
        if key in parsed:
            raise RuleError(f"Duplicate rule for {table}.{field}")
        av = r["AllowedValues"]
        branches_raw = av if isinstance(av, list) else [av]  # array => OR, object => single branch
        norm = []
        for b in branches_raw:
            domain = [k for k in b if k in DOMAIN_KEYS]
            if len(domain) != 1:
                raise RuleError(f"{table}.{field}: branch needs exactly one domain constraint, got {domain}: {b}")
            guards = tuple((_to_node(k, table, tables), v) for k, v in b.items() if k not in DOMAIN_KEYS)
            norm.append((guards, domain[0], b[domain[0]]))
        parsed[key] = norm

    # 3/7. Parse Range_C once and compile each branch to a closure.
    rules: dict[Node, FieldRule] = {}
    edges: dict[Node, set[Node]] = {}
    nodes: set[Node] = set(parsed)
    for key, norm in parsed.items():
        branches: list[Branch] = []
        deps: set[Node] = set()
        for guards, constraint, spec in norm:
            check, refs = _compile_check(constraint, spec, key[0], tables, guards)
            branches.append(Branch(guards, constraint, spec, refs, check))
            # 5. Link: refs from guards and Range_C become dependency edges.
            deps.update(g[0] for g in guards)
            deps.update(refs)
        rules[key] = FieldRule(key[0], key[1], tuple(branches), frozenset(deps))
        for d in deps:
            nodes.add(d)
            edges.setdefault(d, set()).add(key)

    # 6. Topological sort (fail fast on cycles).
    order = _kahn(nodes, edges)

    # 4/8. Index (hash map on (table, field)) and freeze.
    graph = MappingProxyType({n: tuple(sorted(d)) for n, d in edges.items()})
    return Registry(version, MappingProxyType(rules), tuple(order), graph)


def load_rules(path: str | Path = DEFAULT_RULES_PATH) -> Registry:
    data = Path(path).read_bytes()
    raw = json.loads(data)
    if not isinstance(raw, list):
        raise RuleError("Rule file must be a JSON array")
    return build_registry(raw, version=hashlib.sha256(data).hexdigest()[:12])


# --------------------------------------------------------------------------- #
# Cached singleton with hot reload
# --------------------------------------------------------------------------- #
class RegistryHolder:
    """Immutable registry singleton; reload() swaps atomically when the file's content hash changes.

    A failed reload keeps serving the previous registry.
    """

    def __init__(self, path: str | Path = DEFAULT_RULES_PATH):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._registry = load_rules(self._path)

    @property
    def registry(self) -> Registry:
        return self._registry

    def reload(self) -> bool:
        with self._lock:
            digest = hashlib.sha256(self._path.read_bytes()).hexdigest()[:12]
            if digest == self._registry.version:
                return False
            self._registry = load_rules(self._path)  # raises -> old registry kept
            return True


_holder: RegistryHolder | None = None


def get_registry(path: str | Path = DEFAULT_RULES_PATH) -> Registry:
    global _holder
    if _holder is None:
        _holder = RegistryHolder(path)
    return _holder.registry


def export_registry(reg: Registry) -> dict[str, Any]:
    """Human-readable snapshot of the compiled registry (closures are summarised, not serialised)."""
    def branch(b: Branch) -> dict[str, Any]:
        return {
            "guards": {f"{t}.{f}": v for (t, f), v in b.guards},
            "constraint": b.constraint,
            "allowed": b.spec,
            "refs": [f"{t}.{f}" for t, f in b.refs],
        }

    return {
        "version": reg.version,
        "evaluation_order": [f"{t}.{f}" for t, f in reg.order],
        "dependency_graph": {f"{t}.{f}": [f"{a}.{b}" for a, b in d] for (t, f), d in reg.graph.items()},
        "rules": {
            f"{t}.{f}": {
                "depends_on": sorted(f"{a}.{b}" for a, b in r.deps),
                "branches": [branch(b) for b in r.branches],
            }
            for (t, f), r in reg.rules.items()
        },
    }


if __name__ == "__main__":
    reg = load_rules()
    out = Path(__file__).resolve().parent / "registry_dump.json"
    out.write_text(json.dumps(export_registry(reg), indent=2), encoding="utf-8")
    print(f"version={reg.version} rules={len(reg.rules)} -> {out}")
