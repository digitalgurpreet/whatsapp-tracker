"""Application settings loaded from environment variables and an optional `.env` file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the WhatsApp webhook listener.

    Values are read from process environment variables, falling back to `.env`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    VERIFY_TOKEN: str = "replace-me-with-a-secret-token"
    DATABASE_URL: str = "sqlite:///./whatsapp_chats.db"
    PORT: int = 8000

    # Used to send (and therefore log) outbound Cloud API messages.
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_DISPLAY_PHONE: str = ""
    GRAPH_API_VERSION: str = "v25.0"


@lru_cache()
def get_settings() -> Settings:
    """Return a cached Settings instance so env parsing happens once."""

    return Settings()
