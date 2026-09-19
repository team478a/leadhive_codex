from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore"
    )
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/leadhive_v2"
    cors_origins: str = "http://localhost:5173"
    cookie_secure: bool = False
    session_hours: int = 12

    @field_validator("database_url")
    @classmethod
    def postgres_driver(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("PostgreSQL + psycopg is required")
        return value

    @field_validator("session_hours")
    @classmethod
    def positive_lifetime(cls, value: int) -> int:
        if not 1 <= value <= 168:
            raise ValueError("session_hours must be between 1 and 168")
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
