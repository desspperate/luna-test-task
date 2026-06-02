import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka.integrations import fastapi as fastapi_integration
from fastapi import FastAPI
from loguru import logger

from payments_processor.configs import AppConfig, PGConfig, RMQConfig, WebhookConfig
from payments_processor.di import make_payments_container
from payments_processor.error_handlers import register_error_handler
from payments_processor.middlewares import register_api_key_middleware
from payments_processor.routers import payment_router, ping_pong_router
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
        rmq_config = await container.get(RMQConfig)
        print_pd_settings(rmq_config)
        webhook_config = await container.get(WebhookConfig)
        print_pd_settings(webhook_config)

        yield

        logger.info("Shutting down...")
        await container.close()

    application = FastAPI(
        debug=app_config.DEBUG,
        title=app_config.FASTAPI_TITLE,
        lifespan=lifespan,
    )

    fastapi_integration.setup_dishka(container=container, app=application)

    register_api_key_middleware(app=application, api_key=app_config.API_KEY)

    application.include_router(ping_pong_router)
    application.include_router(payment_router)

    register_error_handler(application)

    return application


app = create_app()
