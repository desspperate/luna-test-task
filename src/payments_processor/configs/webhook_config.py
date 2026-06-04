from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebhookConfig(BaseSettings):
    WEBHOOK_SECRET: SecretStr = Field(..., min_length=32)
    WEBHOOK_TIMEOUT_SECONDS: float = 10.0
    WEBHOOK_ALLOW_PRIVATE_HOSTS: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
