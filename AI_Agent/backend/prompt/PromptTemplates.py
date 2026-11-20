"""All prompt templates live here (see .claude/RULES/PromptFileRule.MD).

Each template is a LangChain ``ChatPromptTemplate`` built with ``from_messages``. Fetch one with
``get_prompt(name, **variables)``; never build prompt strings in other modules.

Templates that carry the conversation use a ``MessagesPlaceholder("history")`` (a list of prior
chat messages, ``[]`` when there is none) followed by the latest user message ``{question}``.

Variables per template:
  intent            history, question
  type-detection    dialect, json_sample
  create-ddl        dialect, history, question, schema_name, table_name, json_sample, type_hints
  key-suggestions   dialect, ddl_script
  alternate-types   dialect, ddl_script, json_sample
  revise-ddl        dialect, ddl_script, type_suggestions
  revision-answer   type_suggestions, answer
  modification-plan dialect, history, question, schema_name, table_name, dependencies,
                    field_changes
``dialect`` is the target database (settings.db_dialect), e.g. PostgreSQL or MySQL.
"""

from langchain_core.messages import BaseMessage as LC_BaseMessage
from langchain_core.prompts import ChatPromptTemplate as LC_ChatPromptTemplate, MessagesPlaceholder as LC_MessagesPlaceholder

TEMPLATES: dict[str, LC_ChatPromptTemplate] = {
    # Node A: what does the user want?
    "intent": LC_ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You route requests for a database DDL assistant. Read the conversation and "
                "the latest message, then decide the user's intent:\n"
                "- create: the user wants a NEW table (usually giving a JSON sample).\n"
                "- modify: the user wants to change an EXISTING table (add, drop, rename or "
                "retype columns, add constraints or indexes, ...).\n"
                "- other: anything else, including questions about already generated scripts "
                "that do not ask for a new script.\n"
                "Also return table_name: the table to change (without schema), as the user "
                "wrote it, if stated or inferable from the conversation, else an empty string. "
                "And related_tables: every OTHER existing table the request mentions or needs "
                "to be read (for example one to copy a structure from), else [].\n"
                'Reply with ONLY a JSON object: {{"intent": "create|modify|other", '
                '"table_name": "<name or empty>", "related_tables": ["<name>"]}}',
            ),
            LC_MessagesPlaceholder("history"),
            ("human", "{question}"),
        ]
    ),
    # Column types of all fields of a JSON sample, in one call (used by B1 and C2).
    "type-detection": LC_ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a {dialect} expert. The user sends a JSON object of field name -> "
                "sample value. For EVERY field choose the best {dialect} column data type for "
                "it. Judge the value, not only its JSON type: a string holding a number, "
                "boolean, date, time, timestamp (with or without time zone) or UUID gets that "
                "type; an object gets the dialect's JSON type; an array gets the dialect's "
                "array type, or its JSON type if it has none; a null carries no information, "
                "so answer 'unknown'. Reply with ONLY a JSON object that maps each field name, "
                'exactly as given, to its type, e.g. {{"field_a": "<type>", "field_b": "<type>"}}',
            ),
            ("human", "{json_sample}"),
        ]
    ),
    # Node B1: CREATE TABLE from a JSON sample.
    "create-ddl": LC_ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a {dialect} expert. Write the DDL to create a table in schema "
                "{schema_name} from the JSON sample below.\n"
                "Table name requested by the user: '{table_name}' (derive a sensible one from the "
                "sample when empty).\n"
                "Rules:\n"
                "- The sample is an object of field name -> sample value. Every key is a column "
                "name; quote an identifier only when it needs it.\n"
                "- Column types were already detected from the sample values. Use them unless "
                "the user asks otherwise:\n{type_hints}\n"
                "- An 'unknown' type (null sample) means use a general text type unless the "
                "conversation says otherwise. An object value is a JSON column: use the "
                "dialect's best JSON type unless the user asks for another. Never create child "
                "tables for it.\n"
                "- Add NOT NULL only when the sample or the user implies it.\n"
                "- Add primary keys, foreign keys or indexes only if the user asked for them; "
                "they are suggested separately.\n"
                "- Honour follow-up changes the user asks for in the conversation.\n"
                "Reply with ONE ```sql code block holding only the script, and nothing else.\n\n"
                "JSON sample:\n{json_sample}",
            ),
            LC_MessagesPlaceholder("history"),
            ("human", "{question}"),
        ]
    ),
    # Node B2: primary key and index suggestions for the generated script.
    "key-suggestions": LC_ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a {dialect} expert. For the CREATE TABLE script the user sends, "
                "suggest a primary key (single or composite; natural or surrogate, with a "
                "one-line reason) and any indexes worth having for typical lookups and joins. "
                "Keep the reasoning to short bullets, then give ONE ```sql code block with the "
                "ALTER TABLE ... ADD PRIMARY KEY and CREATE INDEX statements.",
            ),
            ("human", "{ddl_script}"),
        ]
    ),
    # Node B3: alternate data types for some fields.
    "alternate-types": LC_ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a {dialect} expert. Compare the CREATE TABLE script with the JSON "
                "sample it came from and point out columns whose data type could reasonably be "
                "another {dialect} type (for example text -> uuid, a timestamp type, a decimal "
                "with precision, an enum, or integer -> bigint). List only changes worth making, as a markdown "
                "table with the columns: column | current | suggested | why. If none, reply "
                "'No changes suggested.'\n\nJSON sample:\n{json_sample}",
            ),
            ("human", "{ddl_script}"),
        ]
    ),
    # Node B1 again, after the user accepted B3's suggestions (B4): apply them to the script.
    "revise-ddl": LC_ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a {dialect} expert. Rewrite the CREATE TABLE script the user sends, "
                "applying the suggested type changes below. Keep every other column, name, "
                "nullability and constraint exactly as it is.\n"
                "Reply with ONE ```sql code block holding only the script, and nothing else.\n\n"
                "Suggested type changes:\n{type_suggestions}",
            ),
            ("human", "{ddl_script}"),
        ]
    ),
    # Node B4: read the user's reply to "regenerate the CREATE script with these types?".
    "revision-answer": LC_ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You read the user's reply to a question. The assistant suggested these data type "
                "changes for a CREATE TABLE script and asked whether to regenerate the script with "
                "ALL of them:\n\n{type_suggestions}\n\n"
                "Answer Y only if the user clearly agrees to apply all the suggested changes, with "
                "no condition or exception. Answer N for anything else: a refusal, a partial or "
                "conditional yes ('yes, but not all', 'yes, but skip these fields', 'yes, but let "
                "me do it'), an unclear reply, or an unrelated message. "
                "Reply with ONLY the single letter Y or N, nothing else.",
            ),
            ("human", "{answer}"),
        ]
    ),
    # Node C2: ALTER or recreate.
    "modification-plan": LC_ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a {dialect} expert. The user wants to modify the existing table "
                "{schema_name}.{table_name}. Unless the request says otherwise, change only that "
                "table; any other table below is there for reference.\n"
                "The application has ALREADY READ the schemas below live from the database: "
                "they are complete and authoritative. Never say you lack database access and "
                "never simulate or invent a schema. Use the identifiers exactly as shown "
                "(quoted names keep their quotes). For each table you get its columns, "
                "constraints, indexes and the foreign keys of other tables pointing at it:\n\n"
                "{dependencies}\n\n"
                "Fields the user pasted as a PARTIAL JSON sample of this table. Only these fields "
                "need changes; leave every other column untouched. A NEW column must be added; "
                "for an existing column change its type only when the sample's detected type "
                "really differs from the current one (e.g. varchar(50) vs text is no change):\n"
                "{field_changes}\n\n"
                "Decide between ALTER and RECREATE:\n"
                "- ALTER when the change is additive or metadata-only (add column, rename, drop "
                "column, add or drop constraint or index, widen a type).\n"
                "- RECREATE when ALTER would be unsafe or impossible (a type change with no "
                "implicit cast, reordering columns, changes that break dependent foreign keys). "
                "A recreate script must create the new table, copy the data, drop and re-add the "
                "dependent foreign keys, drop the old table and rename the new one.\n"
                "Start your reply with exactly 'Decision: ALTER' or 'Decision: RECREATE', then "
                "give short reasons, naming the dependent tables affected, then ONE ```sql code "
                "block with the complete script.",
            ),
            LC_MessagesPlaceholder("history"),
            ("human", "{question}"),
        ]
    ),
}


def get_prompt(name: str, **variables) -> list[LC_BaseMessage]:
    """Return the chat messages of template ``name`` filled with ``variables``.

    Raises ValueError for an unknown name (listing the valid ones) and for missing or unknown
    variables.
    """
    try:
        template = TEMPLATES[name]
    except KeyError:
        raise ValueError(
            f"Unknown prompt template {name!r}. Valid names: {', '.join(sorted(TEMPLATES))}"
        ) from None

    needed = set(template.input_variables)
    missing, unknown = needed - variables.keys(), variables.keys() - needed
    if missing:
        raise ValueError(f"Prompt {name!r} is missing variable(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"Prompt {name!r} got unknown variable(s): {', '.join(sorted(unknown))}")
    return template.format_messages(**variables)
