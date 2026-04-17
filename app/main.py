from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

import logging

from app.bootstrap import reap_stuck_enrich_jobs, run_migrations
from app.config import settings
from app.database import Base, engine
from app.migrations_runtime import run_all as run_runtime_migrations
from app.observability import (
    RequestIdMiddleware,
    configure_logging,
    configure_sentry,
)

configure_logging()
configure_sentry()
from app.routers.auth_users import router as auth_users_router
from app.routers.auth_ml import router as auth_ml_router
from app.routers.batches import router as batches_router
from app.routers.jobs import router as jobs_router
from app.routers.knowledge_base import router as kb_router
from app.routers.listings import router as listings_router
from app.routers.metrics import router as metrics_router
from app.routers.products import router as products_router
from app.services.mercadolivre import MLAPIError

_logger = logging.getLogger(__name__)


def _validate_crypto_startup() -> None:
    """Falha cedo se secrets críticos não funcionarem. Fail-fast > falha em runtime."""
    if settings.env.lower() == "production" or settings.encryption_key:
        from app.services.crypto import encrypt, decrypt
        probe = encrypt("healthcheck")
        if decrypt(probe) != "healthcheck":
            raise RuntimeError("Fernet round-trip falhou — ENCRYPTION_KEY inválida.")
        _logger.info("crypto OK")

    if settings.env.lower() == "production" and (
        not settings.jwt_secret or len(settings.jwt_secret) < 32
    ):
        raise RuntimeError("JWT_SECRET inválida em produção (mínimo 32 chars).")


_validate_crypto_startup()
run_runtime_migrations()
run_migrations()
reap_stuck_enrich_jobs()

app = FastAPI(
    title="OEM Moto -> Mercado Livre",
    version="0.2.0",
    openapi_version="3.0.3",
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # 'unsafe-inline' em script-src: frontend gera handlers onclick via
        # innerHTML (~33 ocorrências). Refatorar para addEventListener é follow-up;
        # CSP ainda bloqueia script externo e eval().
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIdMiddleware)

# CORS — whitelist via settings.allowed_origins.
# Nunca usar ["*"] com allow_credentials=True (abre CSRF cross-origin).
# Auth atual é JWT em Authorization header — CSRF não é vetor enquanto não
# usarmos cookies; ver docs/adr/0001-auth-cors-csrf.md.
_cors_origins = settings.cors_origins()
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

# Static files
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Uploaded images — diretório criado mas NÃO servido via StaticFiles
# Imagens são servidas pelo endpoint autenticado GET /products/{id}/images/{filename}
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Routers
app.include_router(auth_users_router)
app.include_router(auth_ml_router)
app.include_router(batches_router)
app.include_router(products_router)
app.include_router(listings_router)
app.include_router(kb_router)
app.include_router(jobs_router)
app.include_router(metrics_router)


@app.exception_handler(MLAPIError)
async def ml_api_error_handler(_request: Request, exc: MLAPIError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


_INDEX_HTML = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    return _INDEX_HTML
