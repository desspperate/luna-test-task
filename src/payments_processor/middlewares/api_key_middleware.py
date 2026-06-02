from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import Response
from pydantic import SecretStr

from payments_processor.constants import PaymentsConstants
from payments_processor.errors import InvalidAPIKeyError, MissingAPIKeyError
from payments_processor.utils import verify_api_key

CallNext = Callable[[Request], Awaitable[Response]]


def register_api_key_middleware(app: FastAPI, api_key: SecretStr) -> None:
    @app.middleware("http")
    async def _api_key_middleware(request: Request, call_next: CallNext) -> Response:
        path = request.url.path
        if path == PaymentsConstants.HEALTH_PATH or path in PaymentsConstants.DOCS_PATHS:
            return await call_next(request)

        provided = request.headers.get(PaymentsConstants.API_KEY_HEADER)
        if provided is None:
            raise MissingAPIKeyError()
        if not verify_api_key(provided=SecretStr(provided), expected=api_key):
            raise InvalidAPIKeyError()

        return await call_next(request)
