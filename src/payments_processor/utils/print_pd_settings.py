from loguru import logger
from pydantic_settings import BaseSettings


def print_pd_settings(pydantic_settings: BaseSettings) -> None:
    logger.info(f"[{pydantic_settings.__class__.__name__}]")

    for k, v in pydantic_settings.model_dump().items():
        logger.info(f"  {k}: {v}")
