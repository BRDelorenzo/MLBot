import os

from cryptography.fernet import Fernet

# Precisa estar setado antes do import de app.main (startup valida Fernet).
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests-only-32c")
os.environ.setdefault("ENV", "development")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite:///./test_oem_ml.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    # Limpa caches entre testes
    from app.services.ai_enrichment import _provider_cache
    _provider_cache.clear()
    from app.services.rate_limit import _backend
    if hasattr(_backend, "_requests"):
        _backend._requests.clear()


@pytest.fixture()
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        # Register a test user and attach auth headers by default
        c.post("/auth/register", json={"name": "Test User", "email": "test@test.com", "password": "TestUser!2345"})
        login = c.post("/auth/login", json={"email": "test@test.com", "password": "TestUser!2345"})
        token = login.json().get("token", "")
        c.headers.update({"Authorization": f"Bearer {token}"})
        # Expose authenticated user_id for tests that precisam semear dados multi-tenant.
        from app.models import User
        u = db.query(User).filter(User.email == "test@test.com").first()
        c.user_id = u.id if u else None
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def user_id(client):
    """Retorna o id do usuário autenticado injetado pelo fixture `client`."""
    return client.user_id
