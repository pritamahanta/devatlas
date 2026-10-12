from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://devatlas:devatlas@localhost:5432/devatlas"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    embed_backend: str = "sentence-transformers"  # or "hash" (offline tests/CI only)
    query_prefix: str = "Represent this sentence for searching relevant passages: "  # bge
    candidates_per_retriever: int = 30
    rrf_k: int = 60
    hnsw_ef_search: int = 200


settings = Settings()
