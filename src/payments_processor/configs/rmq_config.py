from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RMQConfig(BaseSettings):
    RMQ_USER: str
    RMQ_PASSWORD: SecretStr
    RMQ_HOST: str
    RMQ_PORT: int
    RMQ_VHOST: str = "/"

    @property
    def url(self) -> str:
        return (
            f"amqp://{self.RMQ_USER}:{self.RMQ_PASSWORD.get_secret_value()}"
            f"@{self.RMQ_HOST}:{self.RMQ_PORT}{self.RMQ_VHOST}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
