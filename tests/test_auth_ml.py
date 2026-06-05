"""Testes do fluxo OAuth do Mercado Livre (PKCE + troca de code por token).

Cobrem a causa raiz do 500 em produção: a URL de autorização não pedia o scope
`offline_access`, então o ML não devolvia `refresh_token` e o parsing quebrava
com KeyError (exceção não-MLAPIError → 500 Internal Server Error).
"""

from datetime import UTC, datetime

import pytest

from app.models import MLCredential
from app.services import mercadolivre
from app.services.mercadolivre import (
    MLAPIError,
    exchange_code_for_token,
    get_auth_url,
)
from app.services.oauth_state import sign_state


class _FakeResp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp: _FakeResp):
        self._resp = resp
        self.calls: list = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._resp


def _seed_credential(db, user_id: int = 1) -> str:
    """Simula o estado pós get_auth_url: verifier + state persistidos."""
    state = sign_state(user_id)
    cred = MLCredential(
        user_id=user_id,
        access_token_encrypted="",
        refresh_token_encrypted="",
        expires_at=datetime.now(UTC).replace(tzinfo=None),
        pkce_verifier=mercadolivre.encrypt("verifier-xyz"),
        oauth_state=state,
    )
    db.add(cred)
    db.commit()
    return state


def test_get_auth_url_requests_offline_access_scope(db):
    """Sem offline_access o ML não devolve refresh_token. A URL precisa pedi-lo."""
    url = get_auth_url(db, user_id=1)
    assert "scope=" in url
    assert "offline_access" in url


def test_exchange_without_refresh_token_raises_mlapierror_not_500(db, monkeypatch):
    """ML 200 sem refresh_token deve virar MLAPIError limpo, nunca KeyError/500."""
    state = _seed_credential(db, user_id=1)
    resp = _FakeResp(
        200,
        {"access_token": "AT", "expires_in": 3600, "token_type": "Bearer", "user_id": 99},
    )
    monkeypatch.setattr(mercadolivre, "_get_http_client", lambda *a, **k: _FakeClient(resp))

    with pytest.raises(MLAPIError):
        exchange_code_for_token("TG-abc", db, state=state)


def test_exchange_happy_path_stores_tokens(db, monkeypatch):
    """Resposta completa do ML grava tokens cifrados e limpa o estado one-shot."""
    state = _seed_credential(db, user_id=1)
    resp = _FakeResp(
        200,
        {
            "access_token": "AT",
            "refresh_token": "RT",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "offline_access read write",
            "user_id": 99,
        },
    )
    monkeypatch.setattr(mercadolivre, "_get_http_client", lambda *a, **k: _FakeClient(resp))

    cred = exchange_code_for_token("TG-abc", db, state=state)

    assert mercadolivre.decrypt(cred.access_token_encrypted) == "AT"
    assert mercadolivre.decrypt(cred.refresh_token_encrypted) == "RT"
    assert cred.ml_user_id == "99"
    assert cred.oauth_state is None
    assert cred.pkce_verifier is None


def test_exchange_db_error_raises_diagnostic(db, monkeypatch):
    """Erro de banco no commit vira MLAPIError com diagnóstico de tamanhos."""
    from sqlalchemy.exc import SQLAlchemyError

    state = _seed_credential(db, user_id=1)
    resp = _FakeResp(
        200,
        {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600, "token_type": "Bearer", "user_id": 99},
    )
    monkeypatch.setattr(mercadolivre, "_get_http_client", lambda *a, **k: _FakeClient(resp))

    def _boom():
        raise SQLAlchemyError("value too long")

    monkeypatch.setattr(db, "commit", _boom)

    with pytest.raises(MLAPIError) as ei:
        exchange_code_for_token("TG-abc", db, state=state)

    assert "DBError" in ei.value.detail
    assert "schema[" in ei.value.detail
    assert "access_token_encrypted" in ei.value.detail


_FULL_TOKEN_PAYLOAD = {
    "access_token": "AT",
    "refresh_token": "RT",
    "expires_in": 3600,
    "token_type": "Bearer",
    "scope": "offline_access read write",
    "user_id": 99,
}


def test_callback_redirects_to_frontend_on_success(client, db, monkeypatch):
    """O callback (navegação do browser) deve redirecionar pra interface, não JSON."""
    state = _seed_credential(db, user_id=client.user_id)
    monkeypatch.setattr(
        mercadolivre, "_get_http_client", lambda *a, **k: _FakeClient(_FakeResp(200, _FULL_TOKEN_PAYLOAD))
    )

    r = client.get(f"/auth/ml/callback?code=TG-x&state={state}", follow_redirects=False)

    assert r.status_code in (302, 303, 307)
    assert "ml=connected" in r.headers["location"]


def test_callback_redirects_with_error_on_failure(client, db, monkeypatch):
    """Falha na troca redireciona pra interface com ml=error, sem 500 cru."""
    state = _seed_credential(db, user_id=client.user_id)
    monkeypatch.setattr(
        mercadolivre,
        "_get_http_client",
        lambda *a, **k: _FakeClient(_FakeResp(400, {"error": "invalid_grant"}, text='{"error":"invalid_grant"}')),
    )

    r = client.get(f"/auth/ml/callback?code=TG-x&state={state}", follow_redirects=False)

    assert r.status_code in (302, 303, 307)
    assert "ml=error" in r.headers["location"]


def test_callback_never_returns_raw_500(client, db, monkeypatch):
    """Exceção inesperada (não-MLAPIError) também vira redirect com detalhe, nunca 500."""
    import app.routers.auth_ml as auth_ml_router

    def _boom(*a, **k):
        raise RuntimeError("kaboom-decrypt")

    monkeypatch.setattr(auth_ml_router, "exchange_code_for_token", _boom)

    r = client.get("/auth/ml/callback?code=TG-x&state=whatever", follow_redirects=False)

    assert r.status_code in (302, 303, 307)
    loc = r.headers["location"]
    assert "ml=error" in loc
    assert "kaboom-decrypt" in loc or "RuntimeError" in loc
