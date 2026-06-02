from collections.abc import AsyncIterable

import httpx
from dishka import Provider, Scope, provide
from loguru import logger


class HttpClientProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_http_client(self) -> AsyncIterable[httpx.AsyncClient]:
        async with httpx.AsyncClient() as client:
            logger.debug("HTTP client created")
            yield client
        logger.debug("HTTP client closed")
