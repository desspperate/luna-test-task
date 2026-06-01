from fastapi import APIRouter

router = APIRouter(
    tags=["Healthcheck"],
)


@router.get("/health")
async def health() -> str:
    return "ok"
