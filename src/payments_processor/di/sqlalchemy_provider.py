from collections.abc import AsyncIterable

from dishka import Provider, Scope, provide
from loguru import logger
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class SqlalchemyProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_database_engine(self, database_url: URL) -> AsyncIterable[AsyncEngine]:
        async_engine = create_async_engine(
            database_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
        )
        logger.debug("Database engine created")
        yield async_engine
        await async_engine.dispose()
        logger.debug("Database engine disposed")

    @provide(scope=Scope.APP)
    async def get_database_session_maker(self, database_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(
            bind=database_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @provide(scope=Scope.REQUEST)
    async def get_database_session(
            self,
            database_session_maker: async_sessionmaker[AsyncSession],
    ) -> AsyncIterable[AsyncSession]:
        async with database_session_maker() as session:
            try:
                with logger.contextualize(session_id=id(session)):
                    yield session
            except Exception:
                await session.rollback()
                raise
