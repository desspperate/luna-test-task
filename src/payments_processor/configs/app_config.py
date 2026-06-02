from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    FASTAPI_TITLE: str
    DEBUG: bool
    LOGURU_LEVEL: str
    API_KEY: SecretStr

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
