from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(
    tags=["Healthcheck"],
    route_class=DishkaRoute,
)


@router.get("/health", include_in_schema=False)
async def health() -> str:
    return "ok"


@router.get("/ready", include_in_schema=False)
async def ready(session: FromDishka[AsyncSession]) -> JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as e:
        logger.exception("/ready: database ping failed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "db_unhealthy",
                "checks": {"database": False},
                "error": type(e).__name__,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ready",
            "checks": {"database": True},
        },
    )
