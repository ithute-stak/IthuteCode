"""HTTP application composition root."""
from fastapi import FastAPI
from pydantic import BaseModel
from .settings import Settings

class HealthResponse(BaseModel):
    status: str
    service: str

def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings.from_env()
    app = FastAPI(
        title="IthuteCode API",
        version="0.1.0",
        docs_url="/docs" if config.environment == "development" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.environment == "development" else None,
    )

    @app.get("/health/live", response_model=HealthResponse)
    def liveness() -> HealthResponse:
        return HealthResponse(status="alive", service="ithutecode-api")

    return app
