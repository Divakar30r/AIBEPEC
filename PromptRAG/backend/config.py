"""All secrets and keywords come from the .env file and are exposed as `settings`."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # OpenAI
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # LLM for evaluation and chat: a Hugging Face model reached through an OpenAI-compatible
    # provider endpoint (HF Inference Providers router by default).
    huggingfacehub_api_token: str = ""
    hf_model_id: str = "Intelligent-Internet/II-Medical-7B-Preview"
    hf_task: str = "conversational"  # chat-style calls; the client always uses chat completions
    hf_max_new_tokens: int = 3000
    hf_temperature: float = 0.2
    hf_provider: str = "featherless-ai"  # appended to the model id as "<model>:<provider>"
    hf_base_url: str = "https://router.huggingface.co/v1"

    # Postgres
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_db: str = "vector_db"
    pg_user: str = "postgres"
    pg_password: str = ""
    table_prefix: str = "PromptRAG"

    # Sources
    git_repo_url: str = (
        "https://github.com/NirDiamant/Prompt_Engineering/tree/main/"
        "all_prompt_engineering_techniques"
    )
    github_token: str = ""
    pdf_dir: str = "data/pdfs"

    # Chunking / search
    text_chunk_size: int = 1000  # PDFs and prose (paragraph-based recursive split)
    text_chunk_overlap: int = 150
    code_chunk_size: int = 1000  # Python code from git (language-based recursive split)
    code_chunk_overlap: int = 100
    chunks_per_file: int = 2  # best-matching chunks kept per file in the RAG output

    @property
    def pdf_path(self) -> Path:
        p = Path(self.pdf_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p


settings = Settings()
