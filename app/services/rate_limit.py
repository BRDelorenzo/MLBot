"""Rate limiter com backend em memória (dev) ou Redis (prod multi-worker).

Escolha via `settings.redis_url`. Em prod sem Redis, o limite é por processo
e multiplicado pelo número de workers — por isso logamos warning.
"""

import logging
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)


class _MemoryBackend:
    """Sliding window em memória. Válido apenas para single-process."""

    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, max_requests: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        bucket = [t for t in self._requests[key] if t > cutoff]
        if len(bucket) >= max_requests:
            self._requests[key] = bucket
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Muitas requisições. Tente novamente em alguns minutos.",
            )
        bucket.append(now)
        self._requests[key] = bucket


class _RedisBackend:
    """Sliding window via Redis sorted set — funciona cross-worker."""

    def __init__(self, url: str):
        import redis  # import tardio: só roda se configurado

        self.client = redis.Redis.from_url(url, decode_responses=True)
        self.client.ping()

    def check(self, key: str, max_requests: int, window_seconds: int) -> None:
        redis_key = f"ratelimit:{key}"
        now_ms = int(time.time() * 1000)
        window_ms = window_seconds * 1000
        try:
            pipe = self.client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, now_ms - window_ms)
            pipe.zadd(redis_key, {f"{now_ms}:{time.monotonic_ns()}": now_ms})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds + 1)
            _, _, count, _ = pipe.execute()
        except HTTPException:
            raise
        except Exception:
            logger.exception("Redis rate limit falhou — fail-closed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limit indisponível temporariamente.",
            )
        if count > max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Muitas requisições. Tente novamente em alguns minutos.",
            )


def _build_backend():
    if settings.redis_url:
        try:
            backend = _RedisBackend(settings.redis_url)
            logger.info("Rate limiter: backend Redis")
            return backend
        except Exception:
            logger.exception("Falha ao conectar Redis para rate limit")
            if settings.env == "production":
                raise
    if settings.env == "production":
        logger.warning(
            "Rate limiter em memória em produção — limite efetivo é "
            "multiplicado pelo número de workers. Configure REDIS_URL."
        )
    return _MemoryBackend()


_backend = _build_backend()


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def check(self, key: str):
        _backend.check(key, self.max_requests, self.window_seconds)


login_limiter = RateLimiter(max_requests=5, window_seconds=60)
register_limiter = RateLimiter(max_requests=3, window_seconds=300)
enrich_limiter = RateLimiter(max_requests=20, window_seconds=60)
publish_limiter = RateLimiter(max_requests=10, window_seconds=60)


def _peer_is_trusted(peer: str | None) -> bool:
    """Checa se o IP imediato do request está entre os proxies confiáveis."""
    if not peer:
        return False
    import ipaddress

    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False

    for item in settings.trusted_proxy_list():
        try:
            if "/" in item:
                if addr in ipaddress.ip_network(item, strict=False):
                    return True
            elif addr == ipaddress.ip_address(item):
                return True
        except ValueError:
            continue
    return False


_warned_no_trusted = False


def get_client_ip(request: Request) -> str:
    """Retorna o IP real do cliente.

    - Se `trusted_proxy` ligado e peer está na lista `trusted_proxies`, lê o
      PRIMEIRO IP do `X-Forwarded-For` (convenção nginx/Cloudflare/ALB).
    - Caso contrário, ignora o header (evita spoofing) e usa `request.client`.
    """
    global _warned_no_trusted

    peer = request.client.host if request.client else None

    if settings.trusted_proxy:
        trusted_list = settings.trusted_proxy_list()
        if not trusted_list:
            if settings.env == "production" and not _warned_no_trusted:
                logger.warning(
                    "trusted_proxy=True mas TRUSTED_PROXIES vazio — "
                    "X-Forwarded-For aceito de qualquer peer é inseguro."
                )
                _warned_no_trusted = True
            trusted_ok = True  # compat dev
        else:
            trusted_ok = _peer_is_trusted(peer)

        if trusted_ok:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()

    return peer or "unknown"
