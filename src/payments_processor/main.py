import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka.integrations import fastapi as fastapi_integration
from fastapi import FastAPI
from loguru import logger

from payments_processor.configs import AppConfig, PGConfig
from payments_processor.di import make_payments_container
from payments_processor.routers import ping_pong_router
from payments_processor.utils import print_pd_settings


def create_app() -> FastAPI:
    logger.remove()
    logger.add(sys.stderr, serialize=True)

    app_config = AppConfig()  # type: ignore[call-args]

    container = make_payments_container(app_config_instance=app_config)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Starting up...")

        print_pd_settings(app_config)
        pg_config = await container.get(PGConfig)
        print_pd_settings(pg_config)

        yield

        logger.info("Shutting down...")
        await container.close()

    application = FastAPI(
        debug=app_config.DEBUG,
        title=app_config.FASTAPI_TITLE,
        lifespan=lifespan,
    )

    fastapi_integration.setup_dishka(container=container, app=application)

    application.include_router(ping_pong_router)

    return application


app = create_app()
