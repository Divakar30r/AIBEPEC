# Chatbot — Prompt Template Comparison

Side-by-side Streamlit app that asks the **same question** to two LangChain
prompt-template strategies and shows the answers plus the exact prompt each one
produced.

| Column | API | Prompt shape |
|---|---|---|
| Left | `ChatPromptTemplate.from_messages()` | Explicit role-tagged messages (`SystemMessage`, `MessagesPlaceholder`, `HumanMessage`) |
| Right | `ChatPromptTemplate.from_template()` | One single string with roles faked as text |

Model: `deepseek-ai/DeepSeek-V4.1-Flash` via **Hugging Face Inference Providers**
(`langchain-huggingface` → `HuggingFaceEndpoint` → `ChatHuggingFace`).

## Setup

```powershell
uv venv
uv pip install -r requirements.txt
Copy-Item .env.example .env      # then paste your HF token into .env
```

`.env` keys:

| Variable | Purpose |
|---|---|
| `HUGGINGFACEHUB_API_TOKEN` | HF access token — required |
| `HF_MODEL_ID` | Repo id, defaults to `deepseek-ai/DeepSeek-V4.1-Flash` |
| `HF_PROVIDER` | `auto` or a live provider: `novita`, `together`, `fireworks-ai`, `featherless-ai`, `baseten`, `deepinfra` |
| `HF_MAX_NEW_TOKENS`, `HF_TEMPERATURE`, `HF_REPETITION_PENALTY` | Generation defaults |

## Run

```powershell
uv run streamlit run src/chatbot/frontend.py
# or
uv run python -m chatbot
```

## Layout

```
src/chatbot/
  config.py    # .env -> Settings dataclass
  llm.py       # HF Inference Providers -> BaseChatModel
  prompts.py   # the two templates + introspection
  backend.py   # Session: history + chain, render_prompt(), ask(), reset()
  frontend.py  # Streamlit UI with two parallel chat columns
  __main__.py  # python -m chatbot
```

See [CLAUDE.MD](./CLAUDE.MD) for project constraints.
