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

Main graph uses stream method - as it updates the nodes status  meaning it runs as stream but can update/get info about notes in the middle
Subgraph uses invoke method - as it just returns the output without any possibilities in the middle

In Python - whichever added as Callable variable, backtracks the variable state over different methods and gets updated instead of traditional return statements


# Refactors
1) Agent did not support related tables, for modification when one more than one table it takes one primary and the other tables were not looked into DB instead hallucinated from it's chat memory. Handled by adding related tables in AgentState
2) Code refactoring was done to remove Postgre specific and keep the dialects configurable, thereby #PromptTemplates.Py modifiied for adding context of dynamic dialect and all regex patterns in #SampleTypes.py for identifying alternate data types were removed and handled via LLM thru appropriate prompts
3) Load dependencies loads all related table info thru table_info method which is converted to a subgraph now (with two nodes - _FindTable_ and _ReadTable_ ) and added as a single node to the main graph The Subgraph was introduced to explore Send() which handles any parallel fan outs

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
├─ backend/                       (1,300 lines)
│  ├─ config.py            41   Settings (.env): HF, db_dialect, PG, history   L10
│  ├─ BackendConstants.py  89   INTENTS L4 · NODES L11 · NODE_LABELS L26 · MESSAGES L41
│  │                            · B4 answer lists L73-77 · script keyword lists L80-89
│  ├─ state.py             65   AgentState L10 · split_messages L45
│  │                            · TableFetchState L54 · TableFetchOutput L64
│  ├─ llm.py               39   get_llm L12 · set_llm L30 · ask L36
│  ├─ prompt/
│  │  └─ PromptTemplates.py 193 TEMPLATES L23: intent L26 · type-detection L49
│  │                            · create-ddl L66 · key-suggestions L95
│  │                            · alternate-types L109 · revise-ddl L124
│  │                            · modification-plan L138 · get_prompt L174
│  ├─ Util.py              84   to_messages L15 · classify_answer L23 · parse_json_object L44
│  │                            · find_json_sample L50 · is_valid_sample L64 · extract_sql L77
│  ├─ SampleTypes.py       63   detect_types L17 · describe_sample L38 · describe_changes L47
│  │
│  │  ── main graph nodes ──
│  ├─ nodes.py            181   A check_intent L25 · B1 create_ddl L48 (revise mode)
│  │                            · B4 ask_revision L72 (interrupt + Command) · C1 load_dependencies L89
│  │                            · fan_out_tables L105 (Send) · routers L114/L128/L135/L141
│  │                            · respond L145
│  ├─ KeySuggestions.py    13   B2 suggest_keys L8
│  ├─ Alternatetypes.py    16   B3 suggest_types L8
│  ├─ Modifications.py     26   C2 plan_modification L10
│  │
│  │  ── subgraph: C1A -> C1B, one run per table ──
│  ├─ SubGraphnodes.py     27   C1A find_table L12 · route_after_find L20 · C1B read_table L24
│  ├─ TableDependencies.py 126  DB access: lookup_table L75 · read_table_info L83
│  │                            · fetch_table_info L110 · table_names L116
│  │                            · table_not_found_message L121 · quote_ident L43
│  │                            · TableInfo L49 · SQL L10-37
│  │
│  ├─ graph.py            100   build_table_fetch_graph L41 · build_graph L52
│  │                            (compiled with InMemorySaver) · graph_mermaid L98
│  │
│  │  ── runtime ──
│  ├─ agent.py            101   _stream L27 (streams node events, detects the B4 pause)
│  │                            · run_agent L62 · resume_agent L80 (Command resume)
│  │                            · run_table_fetch L91 (subgraph on its own, invoke)
│  ├─ db.py                53   connect L9 · connect_target L19 · log_script L28
│  └─ executor.py          83   prepare_statements L26 · summarize_script L53
│                               · execute_script L65
├─ frontend/app.py        258   FLOW L41 · render_flow L70 · run_script L106 · PANE_HEIGHT L125
│                               · on_node L170 · run_turn L192 · resume_turn L210
│                               · handle_question L231 (chat input below it)
└─ tests/test_backend.py  393   50 tests collected; FakeLLM near the top
