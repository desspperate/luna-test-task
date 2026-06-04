import asyncio
import os
import socket
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from aiohttp import web
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.rabbitmq import RabbitMqContainer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    pytest.importorskip("docker")
    container = PostgresContainer(
        "postgres:18-alpine",
        username="test_user",
        password="test_password",
        dbname="test_db",
    )
    try:
        container.start()
    except Exception as e:
        pytest.skip(f"Docker unavailable: {e}")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def rmq_container() -> Iterator[RabbitMqContainer]:
    pytest.importorskip("docker")
    container = RabbitMqContainer(
        "rabbitmq:4.3-management-alpine",
        username="test_user",
        password="test_password",
    )
    try:
        container.start()
    except Exception as e:
        pytest.skip(f"Docker unavailable: {e}")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session", autouse=True)
def _configure_env(pg_container: PostgresContainer, rmq_container: RabbitMqContainer) -> Iterator[None]:
    """Configure env vars to point at the test containers and run migrations once."""
    overrides = {
        "PG_HOST": pg_container.get_container_host_ip(),
        "PG_PORT": str(pg_container.get_exposed_port(5432)),
        "PG_USER": pg_container.username,
        "PG_PASSWORD": pg_container.password,
        "PG_DB": pg_container.dbname,
        "PG_DRIVER": "postgresql+asyncpg",
        "RMQ_HOST": rmq_container.get_container_host_ip(),
        "RMQ_PORT": str(rmq_container.get_exposed_port(5672)),
        "RMQ_USER": "test_user",
        "RMQ_PASSWORD": "test_password",
        "RMQ_VHOST": "/",
        "WEBHOOK_ALLOW_PRIVATE_HOSTS": "1",
        "OUTBOX_BACKOFF_INITIAL_SECONDS": "2",
        "OUTBOX_BACKOFF_MAX_SECONDS": "60",
        "OUTBOX_POLL_INTERVAL_SECONDS": "1",
        "OUTBOX_BATCH_SIZE": "100",
        "CONSUMER_PREFETCH_COUNT": "10",
        "CONSUMER_MAX_RETRIES": "3",
        "CONSUMER_PROCESS_MIN_SECONDS": "0",
        "CONSUMER_PROCESS_MAX_SECONDS": "0.01",
        "CONSUMER_SUCCESS_PROBABILITY": "1.0",
    }
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=repo_root,
        check=True,
        env=os.environ.copy(),
    )

    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(autouse=True)
def _relax_ssrf_schemes() -> Iterator[None]:
    """Allow http:// webhook URLs for integration tests — the local aiohttp
    receiver on 127.0.0.1 doesn't speak TLS. Function-scoped so it doesn't
    leak into other test directories.
    """
    from payments_processor.utils.ssrf_guard import SSRFGuard

    original = SSRFGuard._ALLOWED_SCHEMES
    SSRFGuard._ALLOWED_SCHEMES = frozenset({"https", "http"})
    try:
        yield
    finally:
        SSRFGuard._ALLOWED_SCHEMES = original


def _build_dsn() -> str:
    return (
        f"postgresql+asyncpg://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
        f"@{os.environ['PG_HOST']}:{os.environ['PG_PORT']}/{os.environ['PG_DB']}"
    )


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[Any]:
    eng = create_async_engine(_build_dsn(), pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_maker(engine: Any) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_db(engine: Any) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE payments, outbox RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture
async def pg_session(session_maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_maker() as session:
        yield session


# ---------------------------------------------------------------------------
# Webhook receiver
# ---------------------------------------------------------------------------

ReceivedRequest = dict[str, Any]


class WebhookReceiver:
    def __init__(self, port: int, requests: list[ReceivedRequest], runner: Any) -> None:
        self.port = port
        self.requests = requests
        self.runner = runner
        self._next_status = 200

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/wh"

    def set_status(self, status: int) -> None:
        self._next_status = status


@pytest_asyncio.fixture
async def webhook_receiver() -> AsyncIterator[WebhookReceiver]:
    received: list[ReceivedRequest] = []
    holder: dict[str, int] = {"status": 200}

    async def handler(request: web.Request) -> web.Response:
        body = await request.read()
        received.append(
            {
                "method": request.method,
                "path": request.path,
                "headers": dict(request.headers),
                "body": body,
            },
        )
        return web.Response(status=holder["status"])

    app = web.Application()
    app.router.add_post("/wh", handler)

    port = _free_port()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    receiver = WebhookReceiver(port=port, requests=received, runner=runner)
    receiver._holder = holder  # type: ignore[attr-defined]
    receiver.set_status = lambda s: holder.__setitem__("status", s)  # type: ignore[assignment]

    try:
        yield receiver
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Application (HTTP)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def api_app() -> AsyncIterator[Any]:
    # Re-import per fixture call to pick up env vars; but the container is APP-scoped,
    # so re-creating it gives clean state.
    from payments_processor.configs import AppConfig
    from payments_processor.di import make_payments_container
    from payments_processor.error_handlers import register_error_handler
    from payments_processor.middlewares import register_api_key_middleware
    from payments_processor.routers import api_health_router, payment_router
    from dishka.integrations import fastapi as fastapi_integration
    from fastapi import FastAPI

    app_config = AppConfig()  # type: ignore[call-arg]
    container = make_payments_container(app_config_instance=app_config)
    application = FastAPI(title="test")
    fastapi_integration.setup_dishka(container=container, app=application)
    register_api_key_middleware(app=application, api_key=app_config.API_KEY)
    application.include_router(api_health_router)
    application.include_router(payment_router)
    register_error_handler(application)

    application.state.container = container
    application.state.api_key_value = app_config.API_KEY.get_secret_value()
    try:
        yield application
    finally:
        await container.close()


@pytest_asyncio.fixture
async def api_client(api_app: Any) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=api_app, raise_app_exceptions=False)
    headers = {"X-API-Key": api_app.state.api_key_value}
    async with httpx2.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=headers,
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Helpers exposed for tests
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_headers(api_app: Any) -> dict[str, str]:
    return {"X-API-Key": api_app.state.api_key_value}
