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
    """Callback sem ter feito login primeiro deve dar erro."""
    resp = client.get("/auth/ml/callback?code=FAKE-CODE")
    assert resp.status_code == 400
    assert "code_verifier" in resp.json()["detail"].lower() or "login" in resp.json()["detail"].lower()


def test_auth_login_persists_verifier(client, db):
    """Login deve persistir o PKCE verifier no banco."""
    from app.models import MLCredential

    client.get("/auth/ml/login")
    cred = db.query(MLCredential).first()
    assert cred is not None
    assert cred.pkce_verifier is not None
    assert len(cred.pkce_verifier) > 20
