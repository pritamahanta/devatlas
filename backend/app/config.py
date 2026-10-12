from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")  # backend/.env

    database_url: str = "postgresql://devatlas:devatlas@localhost:5432/devatlas"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    embed_backend: str = "sentence-transformers"  # or "hash" (offline tests/CI only)
    query_prefix: str = "Represent this sentence for searching relevant passages: "  # bge
    candidates_per_retriever: int = 30
    rrf_k: int = 60
    hnsw_ef_search: int = 200

    # --- answering (Step 5) ---
    llm_provider: str = "gemini"        # gemini | anthropic
    llm_model: str = ""                 # empty -> provider default below
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    max_context_chars: int = 24000      # prompt budget for retrieved excerpts
    max_output_tokens: int = 2048
    llm_timeout_s: float = 60.0


settings = Settings()
