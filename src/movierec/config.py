from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration, read from the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # data collection settings
    project_root: Path = Field(
        default=Path(__file__).resolve().parents[2],
        description="Root directory of the project",
    )

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

    # logging settings
    log_dir: Path = Field(
        default=Path("logs"),
        description="Directory for the app's JSON log file, app.jsonl (a volume in Docker)",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Lowest level that is logged",
    )
    log_json: bool = Field(
        default=True,
        description="Print logs as JSON lines (deployment) or as readable text (development). "
        "The log file is always JSON",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _uppercase_log_level(cls, value: object) -> object:
        """Accept log levels in any case, e.g. LOG_LEVEL=debug."""
        return value.upper() if isinstance(value, str) else value

    # API limits
    recommend_rate_per_minute: float = Field(
        default=10,
        gt=0,
        description="POST /recommend calls each client may make per minute, on average",
    )
    recommend_burst: int = Field(
        default=5,
        ge=1,
        description="POST /recommend calls a client may make in a quick burst before the "
        "per-minute rate applies",
    )
    max_jobs_in_flight: int = Field(
        default=8,
        ge=1,
        description="Recommendation jobs pending or running at once; more get a 503",
    )
    job_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        description="How long a finished job's results are kept before they are forgotten",
    )
    max_body_bytes: int = Field(
        default=32_768,
        ge=1024,
        description="Largest request body accepted; larger ones get a 413",
    )

    # monitoring
    metrics_token: SecretStr | None = Field(
        default=None,
        description="Bearer token that GET /metrics requires (at least 16 characters). "
        "Unset, /metrics refuses everyone",
    )

    @field_validator("metrics_token")
    @classmethod
    def _metrics_token_is_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        """Fail at startup on a short, guessable metrics token; treat an empty one as unset."""
        if value is None or value.get_secret_value() == "":
            return None
        if len(value.get_secret_value()) < 16:
            raise ValueError("METRICS_TOKEN must be at least 16 characters")
        return value


settings = Settings()
