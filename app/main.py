from fastapi import FastAPI

from app.database import Base, engine
from app.routers.batches import router as batches_router
from app.routers.products import router as products_router
from app.routers.listings import router as listings_router

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="OEM Moto -> Mercado Livre",
    version="0.1.0",
    openapi_version="3.0.3",
)

app.include_router(batches_router)
app.include_router(products_router)
app.include_router(listings_router)


@app.get("/health")
def healthcheck():
    return {"status": "ok"}