"""Testes focados nas áreas exigidas por B1: auth, crypto, RBAC."""

import os

import pytest

os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkzMmNoYXJzdGVzdGVk")  # 32-byte base64 placeholder


def test_password_policy_rejects_weak():
    from app.services.password_policy import validate_password
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        validate_password("123456")


def test_password_policy_accepts_strong():
    from app.services.password_policy import validate_password
    validate_password("TestUser!2345")


def test_legacy_hash_detection():
    from app.services.auth import is_legacy_hash, hash_password

    legacy = "a" * 32 + ":" + "b" * 64
    assert is_legacy_hash(legacy)
    assert not is_legacy_hash(hash_password("TestUser!2345"))


def test_require_role_denies_non_admin():
    from fastapi import HTTPException
    from app.models import UserRole
    from app.services.auth import require_role

    class FakeUser:
        role = UserRole.operator

    checker = require_role(UserRole.admin)
    with pytest.raises(HTTPException) as exc:
        checker(user=FakeUser())
    assert exc.value.status_code == 403


def test_require_role_allows_admin():
    from app.models import UserRole
    from app.services.auth import require_role

    class FakeUser:
        role = UserRole.admin

    checker = require_role(UserRole.admin)
    assert checker(user=FakeUser()).role == UserRole.admin
