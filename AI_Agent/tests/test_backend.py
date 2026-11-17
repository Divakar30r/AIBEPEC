"""Backend tests. They need no network or database: the LLM is faked and C1 is patched.

Not run automatically; use the /runtests skill.
"""

import json

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from backend import SampleTypes, TableDependencies, agent, graph, llm
from backend.executor import prepare_statements
from backend.prompt import get_prompt
from backend.SampleTypes import describe_changes, detect_types
from backend.textutil import extract_sql, find_json_sample, is_valid_sample, parse_json_object


class FakeLLM(BaseChatModel):
    """Answers by looking at the system prompt, so parallel nodes cannot get each other's reply."""

    intent: str = ""
    calls: list[str] = []  # the system prompt of every call, to count calls per template

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = messages[0].content
        self.calls.append(system)
        if "route requests" in system:
            text = self.intent
        elif "column data type for it" in system:  # type-detection: every field -> "text"
            text = json.dumps({field: "text" for field in json.loads(messages[-1].content)})
        elif "Write the DDL" in system:
            text = "```sql\nCREATE TABLE orders (id int, note text);\n```"
        elif "primary key" in system:
            text = "- use id\n```sql\nALTER TABLE orders ADD PRIMARY KEY (id);\n```"
        elif "another PostgreSQL type" in system:
            text = "No changes suggested."
        else:
            text = "Decision: ALTER\nAdditive.\n```sql\nALTER TABLE orders ADD COLUMN x int;\n```"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def make_llm(intent: str) -> FakeLLM:
    return FakeLLM(intent=intent)


@pytest.fixture(autouse=True)
def reset_llm():
    yield
    llm.set_llm(None)
    agent._graph = None


# --- prompts -------------------------------------------------------------------------------
def test_get_prompt_fills_variables():
    msgs = get_prompt("key-suggestions", dialect="MySQL", ddl_script="CREATE TABLE t (id int);")
    assert msgs[-1].content == "CREATE TABLE t (id int);"
    assert "MySQL expert" in msgs[0].content


def test_get_prompt_history_is_inserted_before_question():
    hist = [HumanMessage(content="hi"), AIMessage(content="hello")]
    msgs = get_prompt("intent", history=hist, question="make a table")
    assert [m.content for m in msgs[1:]] == ["hi", "hello", "make a table"]


def test_get_prompt_unknown_name_lists_valid_names():
    with pytest.raises(ValueError, match="Valid names:.*intent"):
        get_prompt("nope")


def test_get_prompt_missing_and_unknown_variables():
    with pytest.raises(ValueError, match="missing"):
        get_prompt("key-suggestions")
    with pytest.raises(ValueError, match="unknown"):
        get_prompt("key-suggestions", dialect="PostgreSQL", ddl_script="x", extra="y")


# --- text helpers --------------------------------------------------------------------------
def test_find_json_sample_prefers_latest_and_reads_earlier_turns():
    msgs = [
        HumanMessage(content='create table orders {"id": 1, "note": "a"}'),
        AIMessage(content="ok"),
        HumanMessage(content="call it Orders2"),
    ]
    assert '"note": "a"' in find_json_sample(msgs)
    assert find_json_sample([HumanMessage(content="no json here")]) == ""


def test_parse_json_object_inside_prose():
    assert parse_json_object('Sure: {"intent": "create"} done') == {"intent": "create"}
    assert parse_json_object("nothing") is None


def test_extract_sql():
    assert extract_sql("text\n```sql\nSELECT 1;\n```\nmore") == "SELECT 1;"
    assert extract_sql("SELECT 2;") == "SELECT 2;"


@pytest.mark.parametrize(
    "sample, ok",
    [
        ('{"id": "1", "note": "x"}', True),
        ('{"id": 1, "paid": true, "note": null, "tags": ["a"]}', True),
        ('{"id": "1", "address": {"city": "Pune"}}', True),
        ('[{"id": "1"}]', False),
        ("{}", False),
        ("not json", False),
    ],
)
def test_is_valid_sample(sample, ok):
    assert is_valid_sample(sample) is ok


# --- type detection -------------------------------------------------------------------------
def test_detect_types_is_one_llm_call_for_all_fields():
    fake = make_llm("")
    fake.calls = []
    llm.set_llm(fake)
    assert detect_types('{"a": "1", "b": "2", "c": "3"}') == {"a": "text", "b": "text", "c": "text"}
    assert len(fake.calls) == 1


def test_detect_types_forgives_key_case_and_marks_missing_fields_unknown(monkeypatch):
    monkeypatch.setattr(SampleTypes, "ask", lambda name, **kw: 'Sure: {"ID": "integer", "n": ""}')
    assert detect_types('{"id": "1", "n": null, "x": "y"}') == {
        "id": "integer", "n": "unknown", "x": "unknown",
    }


def test_detect_types_passes_the_configured_dialect(monkeypatch):
    seen = {}
    monkeypatch.setattr(SampleTypes, "ask", lambda name, **kw: (seen.update(kw), "{}")[1])
    monkeypatch.setattr(SampleTypes.settings, "db_dialect", "MySQL")
    detect_types('{"a": "1"}')
    assert seen["dialect"] == "MySQL"


def test_describe_changes_marks_new_and_existing_columns():
    llm.set_llm(make_llm(""))
    out = describe_changes('{"status": "Open", "extra": "5"}', {"status": "character varying(20)"})
    assert "status: existing column of type character varying(20); sample suggests text" in out
    assert "extra: NEW column, detected type text" in out


# --- executor guard ------------------------------------------------------------------------
def test_prepare_statements_allows_ddl_and_drops_transaction_control():
    script = "BEGIN; -- c\nCREATE TABLE a (id int);\nALTER TABLE a ADD COLUMN b int;\nCOMMIT;"
    assert prepare_statements(script) == [
        "CREATE TABLE a (id int)",
        "ALTER TABLE a ADD COLUMN b int",
    ]


@pytest.mark.parametrize("script", ["DELETE FROM a", "DROP SCHEMA public CASCADE", "SELECT 1", ""])
def test_prepare_statements_rejects(script):
    with pytest.raises(ValueError):
        prepare_statements(script)


# --- graph ---------------------------------------------------------------------------------
def test_create_with_json_runs_b1_b2_b3():
    llm.set_llm(make_llm('{"intent": "create", "table_name": "orders"}'))
    out = agent.run_agent([], 'create table orders {"id": "1", "note": "x"}')
    assert out.intent == "create"
    assert out.script == "CREATE TABLE orders (id int, note text);"
    assert "PRIMARY KEY" in out.text and "No changes suggested." in out.text


def test_create_without_json_asks_for_it():
    llm.set_llm(make_llm('{"intent": "create", "table_name": "orders"}'))
    out = agent.run_agent([], "create a table for orders")
    assert out.script == "" and "JSON sample" in out.text


def test_invalid_sample_structure_is_rejected():
    llm.set_llm(make_llm('{"intent": "create", "table_name": "orders"}'))
    out = agent.run_agent([], 'create orders [{"id": "1"}]')
    assert out.script == "" and "Invalid structure" in out.text


def test_json_given_in_a_later_turn_is_used():
    llm.set_llm(make_llm('{"intent": "create", "table_name": "orders"}'))
    history = [
        {"role": "user", "content": 'create orders {"id": "1"}'},
        {"role": "assistant", "content": "..."},
    ]
    assert agent.run_agent(history, "rename it to orders2").script.startswith("CREATE TABLE")


def test_modify_runs_c1_c2(monkeypatch):
    monkeypatch.setattr(
        TableDependencies,
        "fetch_table_info",
        lambda name, schema=None: TableDependencies.TableInfo("public", "orders"),
    )
    llm.set_llm(make_llm('{"intent": "modify", "table_name": "orders"}'))
    out = agent.run_agent([], "add column x to orders")
    assert out.intent == "modify" and out.script == "ALTER TABLE orders ADD COLUMN x int;"


def test_modify_json_is_read_from_latest_message_only(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        TableDependencies,
        "fetch_table_info",
        lambda name, schema=None: TableDependencies.TableInfo("public", "orders", column_types={"x": "text"}),
    )
    real_ask = llm.ask

    def spy(name, **kw):
        seen[name] = kw
        return real_ask(name, **kw)

    from backend import Modifications, nodes
    monkeypatch.setattr(Modifications, "ask", spy)
    llm.set_llm(make_llm('{"intent": "modify", "table_name": "orders"}'))
    history = [{"role": "user", "content": 'create orders {"id": "1", "old": "a"}'},
               {"role": "assistant", "content": "..."}]
    agent.run_agent(history, 'change orders {"x": "5"}')
    fc = seen["modification-plan"]["field_changes"]
    assert "x: existing column of type text" in fc and "old" not in fc and "id" not in fc


def test_modify_invalid_json_is_rejected(monkeypatch):
    llm.set_llm(make_llm('{"intent": "modify", "table_name": "orders"}'))
    out = agent.run_agent([], 'change orders [{"x": "5"}]')
    assert out.script == "" and "Invalid structure" in out.text


def test_modify_loads_related_tables_and_stops_if_one_is_missing(monkeypatch):
    seen = {}
    infos = {"orders": TableDependencies.TableInfo("public", "orders", column_types={"x": "text"}),
             "PolMaster": TableDependencies.TableInfo("public", "PolMaster")}
    monkeypatch.setattr(TableDependencies, "fetch_table_info", lambda n, schema=None: infos.get(n))
    from backend import Modifications
    real_ask = llm.ask
    monkeypatch.setattr(Modifications, "ask", lambda name, **kw: (seen.update(kw), real_ask(name, **kw))[1])

    llm.set_llm(make_llm('{"intent": "modify", "table_name": "orders", "related_tables": ["PolMaster"]}'))
    out = agent.run_agent([], "make orders like PolMaster")
    assert out.script.startswith("ALTER")
    assert "public.orders" in seen["dependencies"] and 'public."PolMaster"' in seen["dependencies"]

    llm.set_llm(make_llm('{"intent": "modify", "table_name": "orders", "related_tables": ["ghost"]}'))
    agent._graph = None
    out = agent.run_agent([], "make orders like ghost")
    assert out.script == "" and "`ghost`" in out.text and "PolMaster" not in out.text


def test_quote_ident():
    assert TableDependencies.quote_ident("orders") == "orders"
    assert TableDependencies.quote_ident("PolMaster") == '"PolMaster"'


def test_modify_unknown_table_stops_after_c1(monkeypatch):
    monkeypatch.setattr(TableDependencies, "fetch_table_info", lambda name, schema=None: None)
    llm.set_llm(make_llm('{"intent": "modify", "table_name": "ghost"}'))
    out = agent.run_agent([], "add column x to ghost")
    assert out.script == "" and "ghost" in out.text


def test_other_intent_gets_the_help_text():
    llm.set_llm(make_llm('{"intent": "other", "table_name": ""}'))
    assert "create" in agent.run_agent([], "hello").text


def test_graph_has_every_node():
    assert "plan_modification" in graph.graph_mermaid()
