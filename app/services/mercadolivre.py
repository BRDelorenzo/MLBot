"""Cliente para a API do Mercado Livre (OAuth com PKCE + publicação de itens)."""

import hashlib
import logging
import secrets
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MLCredential
from app.services.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)


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


def get_auth_url(db: Session) -> str:
    code_verifier, code_challenge = _generate_pkce()

    # Persiste o verifier no banco para sobreviver a restarts e múltiplos workers
    credential = db.query(MLCredential).first()
    if not credential:
        credential = MLCredential(
            access_token_encrypted="",
            refresh_token_encrypted="",
            expires_at=_utcnow(),
        )
        db.add(credential)
    credential.pkce_verifier = code_verifier
    db.commit()

    params = {
        "response_type": "code",
        "client_id": settings.ml_app_id,
        "redirect_uri": settings.ml_redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.ml_auth_url}?{urlencode(params)}"


def exchange_code_for_token(code: str, db: Session) -> MLCredential:
    credential = db.query(MLCredential).first()
    code_verifier = credential.pkce_verifier if credential else None

    if not code_verifier:
        raise MLAPIError(400, "Nenhum code_verifier encontrado. Acesse /auth/ml/login primeiro para iniciar o fluxo.")

    payload = {
        "grant_type": "authorization_code",
        "client_id": settings.ml_app_id,
        "client_secret": settings.ml_client_secret,
        "code": code,
        "redirect_uri": settings.ml_redirect_uri,
        "code_verifier": code_verifier,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{settings.ml_api_base_url}/oauth/token", json=payload)

    if resp.status_code != 200:
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

    db.commit()
    db.refresh(credential)
    return credential


def _refresh_token(credential: MLCredential, db: Session) -> MLCredential:
    current_refresh_token = decrypt(credential.refresh_token_encrypted)

    payload = {
        "grant_type": "refresh_token",
        "client_id": settings.ml_app_id,
        "client_secret": settings.ml_client_secret,
        "refresh_token": current_refresh_token,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{settings.ml_api_base_url}/oauth/token", json=payload)

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


def get_valid_token(db: Session) -> str:
    credential = db.query(MLCredential).first()
    if not credential or not credential.access_token_encrypted:
        raise MLAPIError(401, "Nenhuma credencial ML encontrada. Faça a autenticação em /auth/ml/login")

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
        with httpx.Client(timeout=60) as client:
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

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{settings.ml_api_base_url}/items",
            json=body,
            headers=_auth_headers(access_token),
        )

    if resp.status_code not in (200, 201):
        raise MLAPIError(resp.status_code, f"Erro ao publicar item: {resp.text}")

    result = resp.json()

    if description:
        with httpx.Client(timeout=30) as client:
            desc_resp = client.post(
                f"{settings.ml_api_base_url}/items/{result['id']}/description",
                json={"plain_text": description},
                headers=_auth_headers(access_token),
            )
        if desc_resp.status_code not in (200, 201):
            logger.warning("Falha ao enviar descrição para item %s: %s", result["id"], desc_resp.text)

    return result


def predict_category(title: str) -> dict:
    with httpx.Client(timeout=30) as client:
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
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{settings.ml_api_base_url}/sites/{settings.ml_site_id}/categories")

    if resp.status_code != 200:
        raise MLAPIError(resp.status_code, f"Erro ao buscar categorias: {resp.text}")

    return resp.json()


def get_category_attributes(category_id: str) -> list[dict]:
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{settings.ml_api_base_url}/categories/{category_id}/attributes")

    if resp.status_code != 200:
        raise MLAPIError(resp.status_code, f"Erro ao buscar atributos: {resp.text}")

    return resp.json()
