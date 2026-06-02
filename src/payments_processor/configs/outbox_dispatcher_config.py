from pydantic_settings import BaseSettings, SettingsConfigDict


class OutboxDispatcherConfig(BaseSettings):
    OUTBOX_BATCH_SIZE: int = 100
    OUTBOX_POLL_INTERVAL_SECONDS: float = 1.0
    OUTBOX_BACKOFF_INITIAL_SECONDS: float = 2.0
    OUTBOX_BACKOFF_MAX_SECONDS: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
