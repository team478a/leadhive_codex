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
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-luna"
    ai_timeout_seconds: float = 45.0
    ai_max_website_chars: int = 30_000
    worker_lease_seconds: int = 300
    worker_max_attempts: int = 3
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "LeadHive"
    smtp_use_starttls: bool = True
    smtp_timeout_seconds: float = 20.0
    smtp_max_emails_per_day: int = 100
    smtp_minimum_interval_seconds: int = 60
    settings_encryption_key: str = ""

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

    @field_validator("ai_timeout_seconds")
    @classmethod
    def valid_ai_timeout(cls, value: float) -> float:
        if not 1 <= value <= 120:
            raise ValueError("ai_timeout_seconds must be between 1 and 120")
        return value

    @field_validator("ai_max_website_chars")
    @classmethod
    def valid_ai_input_size(cls, value: int) -> int:
        if not 1_000 <= value <= 100_000:
            raise ValueError("ai_max_website_chars must be between 1000 and 100000")
        return value

    @field_validator("worker_lease_seconds")
    @classmethod
    def valid_worker_lease(cls, value: int) -> int:
        if not 60 <= value <= 3600:
            raise ValueError("worker_lease_seconds must be between 60 and 3600")
        return value

    @field_validator("worker_max_attempts")
    @classmethod
    def valid_worker_attempts(cls, value: int) -> int:
        if not 1 <= value <= 10:
            raise ValueError("worker_max_attempts must be between 1 and 10")
        return value

    @field_validator("smtp_port")
    @classmethod
    def valid_smtp_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("smtp_port must be between 1 and 65535")
        return value

    @field_validator("smtp_timeout_seconds")
    @classmethod
    def valid_smtp_timeout(cls, value: float) -> float:
        if not 1 <= value <= 120:
            raise ValueError("smtp_timeout_seconds must be between 1 and 120")
        return value

    @field_validator("smtp_max_emails_per_day")
    @classmethod
    def valid_smtp_daily_limit(cls, value: int) -> int:
        if not 1 <= value <= 10_000:
            raise ValueError("smtp_max_emails_per_day must be between 1 and 10000")
        return value

    @field_validator("smtp_minimum_interval_seconds")
    @classmethod
    def valid_smtp_interval(cls, value: int) -> int:
        if not 0 <= value <= 3600:
            raise ValueError("smtp_minimum_interval_seconds must be between 0 and 3600")
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
