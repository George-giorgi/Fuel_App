from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse

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
from backend.app.core.config import PROJECT_ROOT, get_auth_secret


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_auth_secret()
    yield


app = FastAPI(title="Diesel Desk Fuel API", lifespan=lifespan)
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
