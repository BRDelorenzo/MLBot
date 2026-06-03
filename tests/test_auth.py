def test_auth_status_no_credentials(client):
    resp = client.get("/auth/ml/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is False


def test_auth_login_returns_url(client):
    resp = client.get("/auth/ml/login")
    assert resp.status_code == 200
    data = resp.json()
    assert "auth_url" in data
    assert "code_challenge" in data["auth_url"]
    assert "response_type=code" in data["auth_url"]


def test_auth_callback_without_login(client, db):
    """Callback com state inválido não autentica (proteção HMAC/one-shot).

    O endpoint é de redirect do browser: rejeita redirecionando para /?ml=error,
    nunca para /?ml=connected.
    """
    resp = client.get(
        "/auth/ml/callback?code=FAKE-CODE&state=bogus-unsigned-state",
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303, 307)
    assert "ml=error" in resp.headers["location"]
    assert "ml=connected" not in resp.headers["location"]


def test_auth_login_persists_verifier(client, db):
    """Login deve persistir o PKCE verifier no banco."""
    from app.models import MLCredential

    client.get("/auth/ml/login")
    cred = db.query(MLCredential).first()
    assert cred is not None
    assert cred.pkce_verifier is not None
    assert len(cred.pkce_verifier) > 20
