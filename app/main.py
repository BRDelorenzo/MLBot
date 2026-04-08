from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers.auth_users import router as auth_users_router
from app.routers.auth_ml import router as auth_ml_router
from app.routers.batches import router as batches_router
from app.routers.knowledge_base import router as kb_router
from app.routers.listings import router as listings_router
from app.routers.products import router as products_router
from app.services.mercadolivre import MLAPIError

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="OEM Moto -> Mercado Livre",
    version="0.2.0",
    openapi_version="3.0.3",
)

# Static files
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Routers
app.include_router(auth_users_router)
app.include_router(auth_ml_router)
app.include_router(batches_router)
app.include_router(products_router)
app.include_router(listings_router)
app.include_router(kb_router)


@app.exception_handler(MLAPIError)
async def ml_api_error_handler(_request: Request, exc: MLAPIError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html_path = BASE_DIR / "templates" / "index.html"
    return html_path.read_text(encoding="utf-8")
