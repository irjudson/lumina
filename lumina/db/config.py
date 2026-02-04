"""Database configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database connection settings
    postgres_user: str = "pg"
    postgres_password: str = "buffalo-jump"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "lumina"
    data_dir: str = "/app/data"
    sql_echo: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """Construct PostgreSQL database URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_host_port(self) -> str:
        """Construct PostgreSQL host:port for direct connection."""
        return f"{self.postgres_host}:{self.postgres_port}"

    @property
    def faiss_index_dir(self) -> Path:
        """Get directory for FAISS index files."""
        return Path(self.data_dir) / "faiss_indices"


# Global settings instance
settings = Settings()
