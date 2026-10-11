from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://devatlas:devatlas@localhost:5432/devatlas"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384


settings = Settings()
