from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    FASTAPI_TITLE: str
    DEBUG: bool
    LOGURU_LEVEL: str

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
