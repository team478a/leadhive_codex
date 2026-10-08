"""Runtime application configuration backed by administrator settings."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApplicationSettings
from app.services.email_delivery import decrypt_secret


@dataclass(frozen=True)
class EnvironmentDefaults:
    public_app_url: str
    openai_api_key: str
    openai_model: str
    serper_api_key: str
    google_places_api_key: str
    gbizinfo_api_token: str
    gbizinfo_api_base_url: str


_environment = EnvironmentDefaults(
    public_app_url=settings.public_app_url,
    openai_api_key=settings.openai_api_key,
    openai_model=settings.openai_model,
    serper_api_key=settings.serper_api_key,
    google_places_api_key=settings.google_places_api_key,
    gbizinfo_api_token=settings.gbizinfo_api_token,
    gbizinfo_api_base_url=settings.gbizinfo_api_base_url,
)


def secret_source(ciphertext: str, environment_value: str) -> str:
    if ciphertext:
        return "database"
    return "environment" if environment_value else "unset"


def effective_value(saved_value: str, environment_value: str) -> str:
    return saved_value or environment_value


def apply_application_settings(db: Session) -> None:
    """Apply persisted configuration to this process without logging secret values.

    The worker calls this before each cycle, so configuration changes do not require a
    worker restart. Empty database fields intentionally continue to use environment values.
    """

    saved = db.get(ApplicationSettings, 1)
    if saved is None:
        settings.public_app_url = _environment.public_app_url
        settings.openai_api_key = _environment.openai_api_key
        settings.openai_model = _environment.openai_model
        settings.serper_api_key = _environment.serper_api_key
        settings.google_places_api_key = _environment.google_places_api_key
        settings.gbizinfo_api_token = _environment.gbizinfo_api_token
        settings.gbizinfo_api_base_url = _environment.gbizinfo_api_base_url
        return

    settings.public_app_url = effective_value(saved.public_app_url, _environment.public_app_url)
    settings.openai_model = effective_value(saved.openai_model, _environment.openai_model)
    settings.gbizinfo_api_base_url = effective_value(
        saved.gbizinfo_api_base_url, _environment.gbizinfo_api_base_url
    )
    settings.openai_api_key = (
        decrypt_secret(saved.openai_api_key_ciphertext)
        if saved.openai_api_key_ciphertext
        else _environment.openai_api_key
    )
    settings.serper_api_key = (
        decrypt_secret(saved.serper_api_key_ciphertext)
        if saved.serper_api_key_ciphertext
        else _environment.serper_api_key
    )
    settings.google_places_api_key = (
        decrypt_secret(saved.google_places_api_key_ciphertext)
        if saved.google_places_api_key_ciphertext
        else _environment.google_places_api_key
    )
    settings.gbizinfo_api_token = (
        decrypt_secret(saved.gbizinfo_api_token_ciphertext)
        if saved.gbizinfo_api_token_ciphertext
        else _environment.gbizinfo_api_token
    )
