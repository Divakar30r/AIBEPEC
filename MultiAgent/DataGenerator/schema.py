"""Field list (FieldDesc.MD), rules (registry_dump.json) and the level plan derived from the rule DAG."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from settings import Config

Node = tuple[str, str]  # (table, field) - field may be dotted, e.g. StakerCodes.Unique


def split_ref(ref: str) -> Node:
    table, _, field = ref.partition(".")
    return table, field


def parse_field_desc(text: str) -> dict[str, list[str]]:
    """Tolerant parser for the pseudo-JSON in FieldDesc.MD -> {table: [dotted field names]}."""
    tables: dict[str, list[str]] = {}
    cur: str | None = None
    stack: list[str | None] = []
    for line in text.splitlines():
        s = line.strip()
        head = re.match(r"^#+\s*(\w+)\s*$", s)
        if head:
            cur, stack = head.group(1), []
            tables[cur] = []
            continue
        if cur is None:
            continue
        key = re.match(r'^"(\w+)"\s*:\s*(.*)$', s)
        if key:
            name, rest = key.groups()
            if rest.strip() in ("[", "{"):
                stack.append(name)
            else:
                path = ".".join([x for x in stack if x] + [name])
                if path not in tables[cur]:
                    tables[cur].append(path)
        elif s.startswith(("{", "[")):
            stack.append(None)
        elif s.startswith(("}", "]")) and stack:
            stack.pop()
    return tables


@dataclass(frozen=True)
class Branch:
    guards: tuple[tuple[Node, Any], ...]
    constraint: str
    allowed: Any


@dataclass(frozen=True)
class Plan:
    version: str
    rules: dict[Node, tuple[Branch, ...]]
    levels: tuple[tuple[Node, ...], ...]  # fields per topological level; level 0 has no dependencies

    def level_of(self, node: Node) -> int:
        return next(i for i, lv in enumerate(self.levels) if node in lv)


def build_plan(cfg: Config) -> Plan:
    dump = json.loads(cfg.registry_dump.read_text(encoding="utf-8"))
    rules: dict[Node, tuple[Branch, ...]] = {}
    deps: dict[Node, list[Node]] = {}
    for ref, r in dump["rules"].items():
        node = split_ref(ref)
        rules[node] = tuple(
            Branch(tuple((split_ref(g), v) for g, v in b["guards"].items()), b["constraint"], b["allowed"])
            for b in r["branches"])
        deps[node] = [split_ref(d) for d in r["depends_on"]]

    fields = parse_field_desc(cfg.field_desc.read_text(encoding="utf-8"))
    nodes: list[Node] = [(t, f) for t, fs in fields.items() if t in cfg.tables for f in fs
                         if f != cfg.tables[t].get("key_field", cfg.key_field) and f != cfg.key_field]
    for n in dump["evaluation_order"]:  # rule fields missing from FieldDesc.MD (e.g. Gender) are still generated
        if split_ref(n) not in nodes and split_ref(n)[0] in cfg.tables:
            nodes.append(split_ref(n))

    level: dict[Node, int] = {}
    for ref in dump["evaluation_order"]:  # topological: dependencies precede dependents
        n = split_ref(ref)
        level[n] = 1 + max((level[d] for d in deps.get(n, [])), default=-1)
    for n in nodes:
        level.setdefault(n, 0)  # fields without rules have no dependencies
    top = max((level[n] for n in nodes), default=0)
    levels = tuple(tuple(n for n in nodes if level[n] == i) for i in range(top + 1))
    return Plan(dump["version"], rules, levels)
