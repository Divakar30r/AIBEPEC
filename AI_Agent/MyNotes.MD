# Purpose
LangGraph DDL agent - This is for learning LangGraph

LangGraph is basically revolving around AgentState,  maintaining workflows using nodes and edges(connectors)

Nodes and edges:
A: check_intent (Either create/modify) - expects a sample JSON row (like a row from a noSQL collection) in a standard
if create
B1: Generates DDL script - based on input JSON
B2: Suggests indexes  | B3: Suggests alternate data types as JSON might not be very clear about data type 

if modify:
C1: Loads load_dependencies
C2: Plans modification per the user input

**Agentstate**
   
    # for Node A
    intent,     table_name,     related_tables,     json_sample, json_valid object

    # for B nodes
    ddl_script,  key_suggestions,   type_suggestions

    # for C nodes
    table_found,     missing_tables,     dependencies,    column_types,    modification_plan

    # Output
    script,     reply

    # chat history
    messages

**Flow diagram**
How a request flows:
app.py chat → agent.run_agent → graph.py
  A check_intent ─ create + valid JSON ─→ B1 create_ddl ─┬→ B2 suggest_keys  ─┐
        │                                                └→ B3 suggest_types ─┴→
        └─ modify + table ─→ C1 load_dependencies → C2 plan_modification ──────→ respond
  respond → script pane (right) → executor.execute_script → CP_OrderManagement +



**Execution steps**
!uv run streamlit run frontend/app.py

# UI
1) Basic Workflow on left pane highlighting step running in background
2) Chat conversation on the middle
3) Execute script panel on the right with options to edit and execute w/ button click.

# Things to note
For executing parallel nodes, 
- if we know exactly the number of nodes (Static edges), then multiple nodes passed in an edge - like B2 and B3
- if dynamic loops/routes, need to use Send(Node,state) 
# Refactors
1) Agent did not support related tables, for modification when one more than one table it takes one primary and the other tables were not looked into DB instead hallucinated from it's chat memory. Handled by adding related tables in AgentState
2) Code refactoring was done to remove Postgre specific and keep the dialects configurable, thereby #PromptTemplates.Py modifiied for adding context of dynamic dialect and all regex patterns in #SampleTypes.py for identifying alternate data types were removed and handled via LLM thru appropriate prompts

n) Added a skill command to execute custom command to execute testing

# GitHub branch
https://github.com/Divakar30r/AIBEPEC/tree/AI_Agent_Langgraph

# Project structure

AI_Agent/
├─ CLAUDE.MD                      
├─ pyproject.toml · requirements.txt · uv.lock · .env(.example) · .gitignore
├─ .claude/
│  ├─ RULES/  backend-constants.MD · PromptFileRule.MD
│  └─ skills/runtests/SKILL.md    /runtests runs pytest on demand only
│
├─ backend/                       (1,061 lines)
│  ├─ config.py            41   Settings (.env): HF, db_dialect, PG, history   L10
│  ├─ BackendConstants.py  68   INTENTS L4 · NODES L11 · NODE_LABELS L22 · MESSAG
│  │                            · script keyword lists L59-68
│  ├─ state.py             44   AgentState L9 · split_messages L39
│  ├─ llm.py               39   get_llm L12 · set_llm L30 · ask L36
│  ├─ prompt/
│  │  └─ PromptTemplates.py 178 TEMPLATES L23: intent L25 · type-detection L48
│  │                            · create-ddl L65 · key-suggestions L94
│  │                            · alternate-types L108 · modification-plan L123
│  │                            · get_prompt L159
│  ├─ textutil.py          67   find_json_sample L33 · is_valid_sample L47 · extract_sql L60
│  ├─ SampleTypes.py       63   detect_types L17 · describe_sample L38 · describe
│  │
│  │  ── graph nodes ──
│  ├─ nodes.py            101   A check_intent L14 · B1 create_ddl L37
│  │                            · routers L53/L64 · respond L68
│  ├─ KeySuggestions.py    13   B2 suggest_keys L8
│  ├─ Alternatetypes.py    16   B3 suggest_types L8
│  ├─ TableDependencies.py 134  C1 load_dependencies L107 · fetch_table_info L76
│  │                            · quote_ident L44 · SQL L11-38
│  ├─ Modifications.py     26   C2 plan_modification L10
│  ├─ graph.py             65   build_graph L28 · graph_mermaid L63
│  │
│  │  ── runtime ──
│  ├─ agent.py             53   run_agent L28 (streams node events)
│  ├─ db.py                53   connect L9 · connect_target L19 · log_script L28
│  └─ executor.py          83   prepare_statements L26 · summarize_script L53
│                               · execute_script L65
├─ frontend/app.py        185   FLOW L38 · render_flow L63 · run_script L98
│                               · PANE_HEIGHT L117 (layout and chat below it)
└─ tests/test_backend.py  274   34 tests; FakeLLM near the top

