"""Logging estruturado, request ID correlation e Sentry."""

import contextvars
import logging
import os
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


def configure_logging() -> None:
    """Formato JSON em produção, texto legível em dev."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())

    if settings.env.lower() == "production":
        try:
            from pythonjsonlogger import jsonlogger
            formatter = jsonlogger.JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
                rename_fields={"asctime": "ts", "levelname": "level"},
            )
        except ImportError:
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
            )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def configure_sentry() -> None:
    """Inicializa Sentry somente em produção e se SENTRY_DSN estiver setado."""
    if settings.env.lower() != "production":
        return
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            release=os.getenv("GIT_SHA") or None,
            environment=settings.env,
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logging.getLogger(__name__).info("sentry inicializado")
    except ImportError:
        logging.getLogger(__name__).warning("sentry-sdk não instalado")
