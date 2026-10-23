from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration, read from the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    tmdb_api_key: SecretStr | None = Field(
        default=None,
        description="Hugging Face User Access Token (if using gated/private models)",
    )
    tmdb_base_url: str = Field(
        default="https://api.themoviedb.org/3",
        description="Base URL for TMDB API endpoints",
    )


settings = Settings()
