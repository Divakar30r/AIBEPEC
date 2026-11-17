"""Constant dicts and lists used by the backend (see .claude/RULES/backend-constants.MD)."""

# Values the intent node (A) may return.
INTENTS: dict[str, str] = {
    "create": "create",
    "modify": "modify",
    "other": "other",
}

# LangGraph node names.
NODES: dict[str, str] = {
    "intent": "check_intent",  # A
    "create_ddl": "create_ddl",  # B1
    "suggest_keys": "suggest_keys",  # B2
    "suggest_types": "suggest_types",  # B3
    "load_dependencies": "load_dependencies",  # C1
    "plan_modification": "plan_modification",  # C2
    "respond": "respond",
}

# Display names of the graph nodes (UI flow panel), keyed by node name.
NODE_LABELS: dict[str, str] = {
    "check_intent": "A · Check intent",
    "create_ddl": "B1 · Create DDL",
    "suggest_keys": "B2 · Suggest keys",
    "suggest_types": "B3 · Alternate types",
    "load_dependencies": "C1 · Load dependencies",
    "plan_modification": "C2 · ALTER or recreate",
    "respond": "Respond",
}

# Markdown headings and fixed replies used when composing the final answer.
MESSAGES: dict[str, str] = {
    "ask_json": (
        "To create a table I need a **JSON sample**: an object whose keys are the field names "
        'and whose values are sample values, e.g. `{"order_number": "ORD-1001"}`. '
        "Paste one and tell me the table name."
    ),
    "invalid_structure": (
        "**Invalid structure.** The JSON sample must be a single non-empty object of "
        "`field name: sample value` pairs, e.g. "
        '`{"order_number": "ORD-1001", "qty": 3, "paid": true, "note": null, '
        '"address": {"city": "Pune"}}`. A list of records or a bare value is not accepted.'
    ),
    "ask_table": "Which existing table do you want to modify? Please give its name.",
    "table_not_found": (
        "I could not find {tables} in schema `{schema}` of `{db}`, so I cannot plan the change."
    ),
    "other": (
        "I generate database DDL. Ask me to **create** a table (include a JSON sample) "
        "or to **modify** an existing table."
    ),
    "ddl_intro": "Here is the DDL script:",
    "keys_heading": "### Primary key and index suggestions",
    "types_heading": "### Alternate data type suggestions",
}

# Statements the executor may run; anything else is rejected.
ALLOWED_SCRIPT_KEYWORDS: list[str] = ["CREATE", "ALTER", "DROP", "COMMENT", "INSERT"]

# Transaction control is ignored because the executor wraps the script in one transaction.
IGNORED_SCRIPT_KEYWORDS: list[str] = ["BEGIN", "COMMIT", "END", "START"]

# Never executed, even though DROP is allowed.
FORBIDDEN_SCRIPT_PREFIXES: list[str] = ["DROP DATABASE", "DROP SCHEMA"]

# Language tags accepted on a fenced code block holding SQL.
SQL_FENCE_LANGS: list[str] = ["sql", "pgsql", "postgresql", "plpgsql"]
