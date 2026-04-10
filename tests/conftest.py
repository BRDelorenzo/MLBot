import os

os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1rZXktZm9yLXVuaXQtdGVzdHMtb25seQ==123456=")

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app

# Gera uma chave Fernet válida para testes
_test_key = Fernet.generate_key().decode()
settings.encryption_key = _test_key
settings.jwt_secret = "test-jwt-secret-for-unit-tests-only"

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
    from app.services.rate_limit import login_limiter, register_limiter
    login_limiter._requests.clear()
    register_limiter._requests.clear()


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
        c.post("/auth/register", json={"name": "Test User", "email": "test@test.com", "password": "test123456"})
        login = c.post("/auth/login", json={"email": "test@test.com", "password": "test123456"})
        token = login.json().get("token", "")
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c
    app.dependency_overrides.clear()
