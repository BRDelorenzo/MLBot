"""Assinatura/verificação de OAuth state para o fluxo ML.

O state carrega user_id + timestamp + nonce, assinado com HMAC-SHA256 usando
jwt_secret. O callback valida a assinatura e a validade temporal antes de
confiar no user_id, fechando o vetor de sequestro de conta ML via replay de state.
"""

import hmac
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256

from app.config import settings

STATE_TTL_SECONDS = 600  # 10 minutos


class InvalidStateError(Exception):
    pass


def _secret() -> bytes:
    if not settings.jwt_secret:
        raise RuntimeError("jwt_secret não configurado — state OAuth não pode ser assinado.")
    return settings.jwt_secret.encode("utf-8")


def _b64e(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return urlsafe_b64decode(data + pad)


def sign_state(user_id: int) -> str:
    """Gera state assinado no formato payload.sig (urlsafe b64)."""
    nonce = secrets.token_urlsafe(12)
    payload = f"{user_id}:{int(time.time())}:{nonce}".encode("utf-8")
    sig = hmac.new(_secret(), payload, sha256).digest()
    return f"{_b64e(payload)}.{_b64e(sig)}"


def verify_state(state: str) -> int:
    """Valida HMAC e TTL; retorna user_id. Levanta InvalidStateError se falhar."""
    if not state or "." not in state:
        raise InvalidStateError("state malformado")

    payload_b64, sig_b64 = state.split(".", 1)
    try:
        payload = _b64d(payload_b64)
        sig = _b64d(sig_b64)
    except Exception as exc:
        raise InvalidStateError("state inválido (decode)") from exc

    expected = hmac.new(_secret(), payload, sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise InvalidStateError("assinatura de state inválida")

    try:
        user_id_s, ts_s, _nonce = payload.decode("utf-8").split(":", 2)
        user_id = int(user_id_s)
        ts = int(ts_s)
    except Exception as exc:
        raise InvalidStateError("payload de state inválido") from exc

    if time.time() - ts > STATE_TTL_SECONDS:
        raise InvalidStateError("state expirado")

    return user_id
