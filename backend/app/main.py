from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.routers.admin import router as admin_router
from backend.app.api.routers.auth import router as auth_router
from backend.app.api.routers.dashboard import router as dashboard_router
from backend.app.api.routers.fuel_records import router as fuel_records_router
from backend.app.api.routers.global_meter import router as global_meter_router
from backend.app.api.routers.executive_dashboard import router as executive_dashboard_router
from backend.app.api.routers.inventory import router as inventory_router
from backend.app.api.routers.meter_photos import router as meter_photos_router
from backend.app.api.routers.meter_events import router as meter_events_router
from backend.app.api.routers.vehicles import router as vehicles_router
from backend.app.core.config import (
    PROJECT_ROOT,
    get_auth_secret,
    get_cors_origins,
    validate_cookie_settings,
)
from backend.app.db.session import get_db_session
from backend.app.services.photo_storage import validate_photo_storage_configuration


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_auth_secret()
    validate_cookie_settings()
    validate_photo_storage_configuration()
    yield


app = FastAPI(title="Diesel Desk Fuel API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(dashboard_router)
app.include_router(fuel_records_router)
app.include_router(global_meter_router)
app.include_router(executive_dashboard_router)
app.include_router(inventory_router)
app.include_router(meter_photos_router)
app.include_router(meter_events_router)
app.include_router(vehicles_router)


@app.get("/healthz", include_in_schema=False)
def health_check(
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    session.execute(text("SELECT 1"))
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "index.html")


@app.get("/style.css", include_in_schema=False)
def stylesheet() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "style.css", media_type="text/css")


@app.get("/assets/brusna-curious-cat-logo.png", include_in_schema=False)
def company_logo() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "brusna-curious-cat-logo.png", media_type="image/png"
    )


@app.get("/assets/brusna-cat-favicon-v2.png", include_in_schema=False)
def company_favicon() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "brusna-cat-favicon-v2.png", media_type="image/png"
    )


@app.get("/app.js", include_in_schema=False)
def legacy_frontend_script() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "app.js", media_type="application/javascript"
    )
