"""Cliente para a API do Mercado Livre (OAuth com PKCE + publicação de itens)."""

import hashlib
import logging
import secrets
import threading
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MLCredential
from app.services.crypto import decrypt, encrypt
from app.services.oauth_state import InvalidStateError, sign_state, verify_state

logger = logging.getLogger(__name__)

# Singleton HTTP client com connection pooling
_http_client: httpx.Client | None = None


def _get_http_client(timeout: int = 30) -> httpx.Client:
    global _http_client  # noqa: PLW0603
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(timeout=timeout, limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
    return _http_client


def _utcnow() -> datetime:
    """UTC naive datetime — compatível com SQLite."""
    return datetime.now(UTC).replace(tzinfo=None)


class MLAPIError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _generate_pkce() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def get_auth_url(db: Session, user_id: int) -> str:
    code_verifier, code_challenge = _generate_pkce()
    # State assinado com HMAC: só quem conhece jwt_secret consegue forjar.
    oauth_state = sign_state(user_id)

    # Persiste o verifier e state por usuário (one-shot no callback)
    credential = db.query(MLCredential).filter(MLCredential.user_id == user_id).first()
    if not credential:
        credential = MLCredential(
            user_id=user_id,
            access_token_encrypted="",
            refresh_token_encrypted="",
            expires_at=_utcnow(),
        )
        db.add(credential)
    credential.pkce_verifier = encrypt(code_verifier)
    credential.oauth_state = oauth_state
    db.commit()

    params = {
        "response_type": "code",
        "client_id": settings.ml_app_id,
        "redirect_uri": settings.ml_redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": oauth_state,
    }
    return f"{settings.ml_auth_url}?{urlencode(params)}"


def exchange_code_for_token(code: str, db: Session, state: str | None = None) -> MLCredential:
    # 1. Valida HMAC do state — impede forja/replay cross-user
    if not state:
        raise MLAPIError(400, "Parâmetro state obrigatório para segurança OAuth.")

    try:
        user_id = verify_state(state)
    except InvalidStateError as exc:
        logger.warning("Tentativa de callback OAuth ML com state inválido: %s", exc)
        raise MLAPIError(400, "State OAuth inválido ou expirado.") from exc

    # 2. Busca credencial pelo user_id + state (one-shot: state só é válido se
    #    ainda estiver armazenado; qualquer reuso encontra oauth_state=None).
    credential = (
        db.query(MLCredential)
        .filter(MLCredential.user_id == user_id, MLCredential.oauth_state == state)
        .first()
    )

    if not credential or not credential.pkce_verifier:
        raise MLAPIError(400, "State não corresponde a um fluxo ativo. Reinicie em /auth/ml/login.")

    code_verifier = decrypt(credential.pkce_verifier)

    payload = {
        "grant_type": "authorization_code",
        "client_id": settings.ml_app_id,
        "client_secret": settings.ml_client_secret,
        "code": code,
        "redirect_uri": settings.ml_redirect_uri,
        "code_verifier": code_verifier,
    }

    secret = settings.ml_client_secret or ""
    logger.info(
        "ML token exchange debug | client_id=%r | redirect_uri=%r | secret_len=%d | "
        "secret_has_ws=%s | code_len=%d | code_verifier_len=%d | api_base=%r",
        settings.ml_app_id,
        settings.ml_redirect_uri,
        len(secret),
        secret != secret.strip(),
        len(code),
        len(code_verifier),
        settings.ml_api_base_url,
    )

    client = _get_http_client()
    resp = client.post(f"{settings.ml_api_base_url}/oauth/token", data=payload)

    if resp.status_code != 200:
        logger.warning(
            "ML token exchange rejected | status=%d | body=%r",
            resp.status_code,
            resp.text,
        )
        raise MLAPIError(resp.status_code, f"Erro ao obter token: {resp.text}")

    data = resp.json()
    expires_at = _utcnow() + timedelta(seconds=data["expires_in"])

    credential.access_token_encrypted = encrypt(data["access_token"])
    credential.refresh_token_encrypted = encrypt(data["refresh_token"])
    credential.token_type = data.get("token_type", "Bearer")
    credential.expires_at = expires_at
    credential.scope = data.get("scope", "")
    credential.ml_user_id = str(data.get("user_id", ""))
    credential.pkce_verifier = None  # Limpa após uso
    credential.oauth_state = None

    db.commit()
    db.refresh(credential)
    return credential


# Locks por user_id para serializar refresh_token dentro do mesmo processo.
# Nota: em multi-worker (gunicorn), este lock não cobre entre processos — um
# lock cross-process via Redis/Postgres SELECT FOR UPDATE entra quando A4 for
# feito. Mesmo assim, isso já elimina a race mais comum (mesmo worker).
_refresh_locks_master = threading.Lock()
_refresh_locks: dict[int, threading.Lock] = {}


def _lock_for_user(user_id: int) -> threading.Lock:
    with _refresh_locks_master:
        lock = _refresh_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _refresh_locks[user_id] = lock
        return lock


def _refresh_token(credential: MLCredential, db: Session) -> MLCredential:
    current_refresh_token = decrypt(credential.refresh_token_encrypted)

    payload = {
        "grant_type": "refresh_token",
        "client_id": settings.ml_app_id,
        "client_secret": settings.ml_client_secret,
        "refresh_token": current_refresh_token,
    }

    client = _get_http_client()
    resp = client.post(f"{settings.ml_api_base_url}/oauth/token", data=payload)

    if resp.status_code != 200:
        raise MLAPIError(resp.status_code, f"Erro ao renovar token: {resp.text}")

    data = resp.json()
    credential.access_token_encrypted = encrypt(data["access_token"])
    credential.refresh_token_encrypted = encrypt(data["refresh_token"])
    credential.expires_at = _utcnow() + timedelta(seconds=data["expires_in"])
    credential.scope = data.get("scope", credential.scope)

    db.commit()
    db.refresh(credential)
    return credential


def get_valid_token(db: Session, user_id: int) -> str:
    """Recupera token ML válido do usuário; nunca anônimo para evitar cross-tenant."""
    if not isinstance(user_id, int):
        raise TypeError("get_valid_token exige user_id explícito (int).")

    credential = (
        db.query(MLCredential).filter(MLCredential.user_id == user_id).first()
    )
    if not credential or not credential.access_token_encrypted:
        raise MLAPIError(401, "Nenhuma credencial ML encontrada. Faça a autenticação em /auth/ml/login")

    if _utcnow() >= credential.expires_at:
        # Serializa refresh por usuário para evitar duas threads invalidarem
        # o refresh_token uma da outra. Double-check após adquirir o lock.
        lock = _lock_for_user(credential.user_id)
        with lock:
            db.refresh(credential)
            if _utcnow() >= credential.expires_at:
                credential = _refresh_token(credential, db)

    return decrypt(credential.access_token_encrypted)


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def upload_image(access_token: str, file_path: str) -> str:
    """Faz upload de uma imagem local para o ML e retorna o picture ID."""
    import mimetypes

    mime_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"

    with open(file_path, "rb") as f:
        files = {"file": (file_path.split("/")[-1].split("\\")[-1], f, mime_type)}
        client = _get_http_client()
        resp = client.post(
            f"{settings.ml_api_base_url}/pictures/items/upload",
            files=files,
            headers=_auth_headers(access_token),
        )

    if resp.status_code not in (200, 201):
        raise MLAPIError(resp.status_code, f"Erro ao fazer upload da imagem: {resp.text}")

    data = resp.json()
    picture_id = data.get("id", "")
    logger.info("Imagem enviada ao ML: %s -> id=%s", file_path, picture_id)
    return picture_id


def publish_item(
    access_token: str,
    title: str,
    category_id: str,
    price: float,
    currency_id: str,
    available_quantity: int,
    buying_mode: str,
    condition: str,
    listing_type_id: str,
    description: str,
    pictures: list[dict],
    attributes: list[dict] | None = None,
) -> dict:
    body = {
        "title": title,
        "category_id": category_id,
        "price": price,
        "currency_id": currency_id,
        "available_quantity": available_quantity,
        "buying_mode": buying_mode,
        "condition": condition,
        "listing_type_id": listing_type_id,
        "pictures": pictures,
        "attributes": attributes or [],
    }

    client = _get_http_client()
    resp = client.post(
            f"{settings.ml_api_base_url}/items",
            json=body,
            headers=_auth_headers(access_token),
        )

    if resp.status_code not in (200, 201):
        raise MLAPIError(resp.status_code, f"Erro ao publicar item: {resp.text}")

    result = resp.json()

    if description:
        client = _get_http_client()
        desc_resp = client.post(
            f"{settings.ml_api_base_url}/items/{result['id']}/description",
            json={"plain_text": description},
            headers=_auth_headers(access_token),
        )
        if desc_resp.status_code not in (200, 201):
            logger.warning("Falha ao enviar descrição para item %s: %s", result["id"], desc_resp.text)

    return result


def search_item_by_seller_sku(access_token: str, seller_id: str, sku: str) -> list[str]:
    """Retorna lista de `ml_item_id`s do seller que possuem `seller_sku = sku`.

    A API do ML devolve `results: list[str]` (IDs). Detecta duplicata antes de
    publicar (defesa contra retry após sucesso no ML + falha no commit local).
    """
    if not seller_id or not sku:
        return []
    client = _get_http_client()
    resp = client.get(
        f"{settings.ml_api_base_url}/users/{seller_id}/items/search",
        params={"seller_sku": sku},
        headers=_auth_headers(access_token),
    )
    if resp.status_code != 200:
        logger.warning("Busca por seller_sku %s falhou: %s", sku, resp.status_code)
        return []
    results = resp.json().get("results", []) or []
    # Defensivo: se algum dia vier lista de dicts, extrai o id.
    return [r if isinstance(r, str) else r.get("id") for r in results if r]


def predict_category(title: str) -> dict:
    client = _get_http_client()
    resp = client.get(
        f"{settings.ml_api_base_url}/sites/{settings.ml_site_id}/domain_discovery/search",
        params={"q": title},
    )

    if resp.status_code != 200 or not resp.json():
        raise MLAPIError(resp.status_code, f"Não foi possível prever categoria para: {title}")

    result = resp.json()[0]
    return {
        "category_id": result.get("category_id", ""),
        "category_name": result.get("category_name", ""),
        "domain_id": result.get("domain_id", ""),
        "domain_name": result.get("domain_name", ""),
    }


def get_categories() -> list[dict]:
    client = _get_http_client()
    resp = client.get(f"{settings.ml_api_base_url}/sites/{settings.ml_site_id}/categories")

    if resp.status_code != 200:
        raise MLAPIError(resp.status_code, f"Erro ao buscar categorias: {resp.text}")

    return resp.json()


_CATEGORY_ATTRS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CATEGORY_ATTRS_TTL = 24 * 3600  # 24h


def get_category_attributes(category_id: str) -> list[dict]:
    """Busca atributos da categoria ML com cache de 24h.

    Evita chamar o ML em todo validate/publish — reduz latência e falha menos.
    """
    import time as _t

    cached = _CATEGORY_ATTRS_CACHE.get(category_id)
    if cached and _t.time() - cached[0] < _CATEGORY_ATTRS_TTL:
        return cached[1]

    client = _get_http_client()
    resp = client.get(f"{settings.ml_api_base_url}/categories/{category_id}/attributes")

    if resp.status_code != 200:
        raise MLAPIError(resp.status_code, f"Erro ao buscar atributos: {resp.text}")

    data = resp.json()
    _CATEGORY_ATTRS_CACHE[category_id] = (_t.time(), data)
    return data
