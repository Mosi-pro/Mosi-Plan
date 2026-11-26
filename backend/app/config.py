"""Zentrale Konfiguration aus Umgebungsvariablen (keine Secrets im Code)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://mosi:mosi@localhost:5432/mosi"
    secret_key: str = ""  # Pflicht im Betrieb – wird von install.sh erzeugt
    public_url: str = "http://localhost:8080"
    cookie_secure: bool = True
    session_days: int = 14
    data_dir: str = "/data"
    max_upload_mb: int = 10
    storage_limit_gb: float = 30.0

    # Hermes Agent (OpenAI-kompatibler API-Server des Hermes-Gateways)
    hermes_url: str = "http://hermes:8642"
    hermes_api_key: str = ""
    hermes_enabled: bool = True
    # Token, mit dem Hermes den MOSI-MCP-Endpunkt aufruft
    mcp_token: str = ""

    # Optional: Google OAuth (kann auch über die Einstellungen gesetzt werden)
    google_client_id: str = ""
    google_client_secret: str = ""

    # Direkter KI-Anbieter (Fallback / Alternative zu Hermes), optional per ENV vorbelegt
    ai_direct_base_url: str = ""
    ai_direct_api_key: str = ""
    ai_direct_model: str = ""
    # Startwert für den KI-Modus (hermes | direct | off), solange in den Einstellungen nichts gespeichert ist
    ai_mode: str = ""
    ai_timeout_seconds: int = 300

    disable_jobs: bool = False
    testing: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
