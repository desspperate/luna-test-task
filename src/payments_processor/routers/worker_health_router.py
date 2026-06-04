from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from payments_processor.utils import HealthState

router = APIRouter(
    tags=["Healthcheck"],
)


@router.get("/health", include_in_schema=False)
async def health(request: Request) -> JSONResponse:
    state: HealthState = request.app.state.health

    healthy = state.is_healthy()
    body: dict[str, Any] = {
        "status": "ok" if healthy else "stale",
        "started": state.started,
    }
    if state.last_heartbeat is not None:
        body["last_heartbeat"] = state.last_heartbeat.isoformat()

    return JSONResponse(
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body,
    )
