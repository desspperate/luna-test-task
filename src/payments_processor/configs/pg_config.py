from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PGConfig(BaseSettings):
    PG_USER: str
    PG_PASSWORD: SecretStr
    PG_DB: str
    PG_DRIVER: str
    PG_HOST: str
    PG_PORT: int

    @property
    def dsn(self) -> str:
        return (f"{self.PG_DRIVER}://{self.PG_USER}:{self.PG_PASSWORD.get_secret_value()}@{self.PG_HOST}:{self.PG_PORT}"
                f"/{self.PG_DB}")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
