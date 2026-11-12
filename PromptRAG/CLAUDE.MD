name: Prompt engineering with Git & docs
desc: exploring RAG

# Project Structure

Frontend: UI running on streamlit
Backend:
 - Prompt: For prompt templates
 - Vector: For embedding, chunking and storing into vector DBs
 - Search: User input and semantic search
 - ReadGit: Read a public GitHub repo
 - ReadFiles: Reading .PDF files from a path 


# Database
Use Postgre (on prem) vector for embeddings storage
Use DB 'vector_db' and new tables with prefix 'PromptRAG'

# Token embeddings
Use OpenAI with configurable embedding model

# Variables
All secrets and keywords to be maintained in .env file and loaded via config.py as settings

# Package handling
Use python UV libraries and create .venv, project.toml and requirements.txt

# Git handling
Use GH read only
