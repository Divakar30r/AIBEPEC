name: AI Agent 
desc: exploring Langgraphs for generating sql

# Design

LangGraph: Nodes, edges and optional egdes

Nodes:
- A: Check user intention to create/modify, create needs JSON sample
- B1: DDL Create scripts
- B2: if CREATE script, suggest primary keys
- B3: Alternate data type suggestions for certain fields on top of DDL create script
- B4: after B2 & B3, pause (interrupt) and ask the human whether to redo B1 with B3's suggested types; needs a checkpointer (memory saver)
- C1: if user intends Modification on exisitng, pull Dependent file into context 
- C2: if user intends Modification on exisitng, decide recreation or ALTER script

Edges
A->B1 -> B2 & B3 -> B4 ( if user intends creation; no question when B3 finds nothing to change)
B4 -> B1 -> B2 -> respond (reply Y: B1 redone with B3's types, B2 reruns, B3 does not)
B4 -> respond (any other reply; a separate LLM call reads the reply as Y or N; anything but Y is dropped with a note, so 'yes, but not all' counts as N)
A->C1 -> C2 (if user intends modification)

# Project Structure

Frontend: UI running on streamlit

Backend:
 - Prompt: For prompt templates
 - TableDependencies: Look for any foreign constraints on tables of same schema
 - Alternatetypes: Suggesting alternate data types for fields
 - KeySuggestions: Identify  indexes and provide DDL create scripts
 - Modifications: Suggest recreation or using ALTER scripts

Testing:
 - Test modules not to be auto executed, create a skill to execute it
  

# Database
Use Postgre DB:CP_OrderManagement
Use DB 'vector_db' and new tables with prefix 'PromptRAG'

# LLM
HF model via OpenAI

# Variables
All secrets and keywords to be maintained in .env file and loaded via config.py as settings

# Package handling
Use python UV libraries and create .venv, project.toml and requirements.txt

# Git handling
Use GH read only

