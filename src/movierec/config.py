from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration, read from the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # data collection settings
    tmdb_api_key: SecretStr | None = Field(
        default=None,
        description="Hugging Face User Access Token (if using gated/private models)",
    )
    tmdb_base_url: str = Field(
        default="https://api.themoviedb.org/3",
        description="Base URL for TMDB API endpoints",
    )

    # embedding / ingestion settings
    embed_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="fastembed model used for movies and queries. Changing it creates a new Qdrant collection",
    )
    embed_cache_dir: Path = Field(
        default=Path.home() / ".cache" / "movierec" / "models",
        description="Directory where embedding model weights are cached (a volume in Docker)",
    )
    embed_batch_size: int = Field(
        default=64,
        ge=1,
        description="Texts embedded per batch",
    )
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant server URL (use http://qdrant:6333 inside Docker Compose)",
    )
    qdrant_collection_prefix: str = Field(
        default="movies",
        description="Prefix for the collection name; the model name is appended",
    )
    upsert_batch_size: int = Field(
        default=256,
        ge=1,
        description="Movies embedded and written to Qdrant per chunk during ingest",
    )
    movies_path: Path = Field(
        default=Path.home() / "data" / "clean" / "tmdb_movies.parquet",
        description="Directory where static movie list lives.",
    )


settings = Settings()
