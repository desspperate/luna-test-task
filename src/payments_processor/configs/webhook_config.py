from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebhookConfig(BaseSettings):
    WEBHOOK_SECRET: SecretStr
    WEBHOOK_TIMEOUT_SECONDS: float = 10.0

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
