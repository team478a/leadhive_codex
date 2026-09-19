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
    serper_api_key: str = ""
    google_places_api_key: str = ""
    external_api_timeout_seconds: float = 20.0
    scraper_timeout_seconds: float = 15.0
    scraper_max_bytes: int = 2_000_000
    scraper_user_agent: str = "LeadHiveBot/2.0 (+https://leadhive.work/bot)"

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

    @field_validator("external_api_timeout_seconds")
    @classmethod
    def valid_timeout(cls, value: float) -> float:
        if not 1 <= value <= 60:
            raise ValueError("external_api_timeout_seconds must be between 1 and 60")
        return value

    @field_validator("scraper_timeout_seconds")
    @classmethod
    def valid_scraper_timeout(cls, value: float) -> float:
        if not 1 <= value <= 60:
            raise ValueError("scraper_timeout_seconds must be between 1 and 60")
        return value

    @field_validator("scraper_max_bytes")
    @classmethod
    def valid_scraper_size(cls, value: int) -> int:
        if not 100_000 <= value <= 10_000_000:
            raise ValueError("scraper_max_bytes must be between 100000 and 10000000")
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
