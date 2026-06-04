from pydantic_settings import BaseSettings, SettingsConfigDict


class ConsumerConfig(BaseSettings):
    CONSUMER_PREFETCH_COUNT: int = 10
    CONSUMER_MAX_RETRIES: int = 3
    CONSUMER_PROCESS_MIN_SECONDS: float = 2.0
    CONSUMER_PROCESS_MAX_SECONDS: float = 5.0
    CONSUMER_SUCCESS_PROBABILITY: float = 0.9

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
