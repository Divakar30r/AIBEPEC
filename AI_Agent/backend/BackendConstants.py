"""Constant dicts and lists used by the backend (see .claude/RULES/backend-constants.MD)."""

# Values the intent node (A) may return.
INTENTS: dict[str, str] = {
    "create": "create",
    "modify": "modify",
    "other": "other",
    "drop": "drop",  # only for B4: the reply was not a clear Y, so the revision is dropped
}

# LangGraph node names.
NODES: dict[str, str] = {
    "intent": "check_intent",  # A
    "create_ddl": "create_ddl",  # B1
    "suggest_keys": "suggest_keys",  # B2
    "suggest_types": "suggest_types",  # B3
    "ask_revision": "ask_revision",  # B4 (pauses: asks the human whether to redo B1 with B3's types)
    "fetch_table": "fetch_table",  # subgraph run once per table via Send; holds C1A and C1B
    "find_table": "find_table",  # C1A (inside the subgraph)
    "read_table": "read_table",  # C1B (inside the subgraph)
    "load_dependencies": "load_dependencies",  # C1 (joins the per-table results)
    "plan_modification": "plan_modification",  # C2
    "respond": "respond",
}

# Display names of the graph nodes (UI flow panel), keyed by node name.
NODE_LABELS: dict[str, str] = {
    "check_intent": "A · Check intent",
    "create_ddl": "B1 · Create DDL",
    "suggest_keys": "B2 · Suggest keys",
    "suggest_types": "B3 · Alternate types",
    "ask_revision": "B4 · Ask: revise DDL?",
    "fetch_table": "C1 · Fetch table (per table)",
    "find_table": "C1A · Find table",
    "read_table": "C1B · Read table details",
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
    # Node B4: the question that pauses the graph, and what replaces the B3 table afterwards.
    "revise_question": (
        "Node B3 suggests these data type changes:\n\n{type_suggestions}\n\n"
        "**Regenerate the CREATE script with these types?** Reply **Y**, or just continue chatting."
    ),
    "types_applied": "The suggested data types above were applied to the script.",
    # Added to the final answer when the reply to B4's question was not a clear yes or no.
    "drop_msg": (
        "Unable to confirm whether you wanted the revision, so I dropped this conversation.\n"
        "Please note that the current limitation is that I can either change all suggestions "
        "or nothing."
    ),
}

# Node B3 answers this when nothing is worth changing; B4 then does not ask (compared lower-cased).
NO_CHANGES_MARKER = "no changes suggested"

# Statements the executor may run; anything else is rejected.
ALLOWED_SCRIPT_KEYWORDS: list[str] = ["CREATE", "ALTER", "DROP", "COMMENT", "INSERT"]

# Transaction control is ignored because the executor wraps the script in one transaction.
IGNORED_SCRIPT_KEYWORDS: list[str] = ["BEGIN", "COMMIT", "END", "START"]

# Never executed, even though DROP is allowed.
FORBIDDEN_SCRIPT_PREFIXES: list[str] = ["DROP DATABASE", "DROP SCHEMA"]

# Language tags accepted on a fenced code block holding SQL.
SQL_FENCE_LANGS: list[str] = ["sql", "pgsql", "postgresql", "plpgsql"]
