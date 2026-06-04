from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    FASTAPI_TITLE: str
    DEBUG: bool
    LOGURU_LEVEL: str
    API_KEY: SecretStr = Field(..., min_length=32)

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
