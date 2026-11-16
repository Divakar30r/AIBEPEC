"""All secrets and keywords come from the .env file and are exposed as `settings`."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM: a Hugging Face model reached through an OpenAI-compatible endpoint.
    huggingfacehub_api_token: str = ""
    hf_model_id: str = "Qwen/Qwen2.5-Coder-32B-Instruct"
    hf_provider: str = "featherless-ai"  # optional, appended to the model id as "<model>:<provider>"
    hf_base_url: str = "https://router.huggingface.co/v1"
    hf_max_new_tokens: int = 2000
    hf_temperature: float = 0.1

    # Postgres (local)
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "postgres"
    pg_password: str = "postgres"
    pg_target_db: str = "CP_OrderManagement"  # DDL is generated for / executed against this DB
    target_schema: str = "public"
    pg_log_db: str = "vector_db"  # holds the <table_prefix>_* tables
    table_prefix: str = "PromptRAG"

    # Chat
    history_messages: int = 12  # most recent chat messages passed to the LLM as history


settings = Settings()
