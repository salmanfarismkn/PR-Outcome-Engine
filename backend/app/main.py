from fastapi import FastAPI

from app.api.router import router as api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.ml.router import router as ml_router

configure_logging()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(api_router)
app.include_router(ml_router)


@app.get("/")
async def root():
    return {
        "application": settings.app_name,
        "status": "running",
        "version": "0.1.0",
    }

