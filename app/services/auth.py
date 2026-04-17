"""Serviço de autenticação — registro, login, JWT."""

import logging
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.config import settings
from app.database import get_db
from app.models import User, UserRole
from app.services.password_policy import validate_password

security = HTTPBearer(auto_error=False)


def _get_jwt_secret() -> str:
    if not settings.jwt_secret:
        raise RuntimeError(
            "JWT_SECRET não configurada. "
            "Gere com: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    return settings.jwt_secret


def hash_password(password: str) -> str:
    """Hash seguro com bcrypt (cost factor 12)."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def is_legacy_hash(password_hash: str) -> bool:
    return ":" in password_hash and len(password_hash) == 97


def verify_password(password: str, password_hash: str) -> bool:
    # Suporte a hashes legados SHA-256 (salt:hex) para migração
    if is_legacy_hash(password_hash):
        from hashlib import sha256
        salt, h = password_hash.split(":", 1)
        if sha256(f"{salt}{password}".encode()).hexdigest() == h:
            return True
        return False
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "exp": datetime.now(UTC) + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")


class EmailAlreadyRegistered(Exception):
    """Sinaliza que o email já existe — o router decide se responde genérico."""


def register_user(name: str, email: str, password: str, db: Session) -> User:
    # Valida senha ANTES de tocar no DB — evita vazar existência via timing de
    # query. A mensagem de política é pública e não revela nada sobre o email.
    validate_password(password)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        logger.info("register: tentativa com email já cadastrado (enum blocked)")
        raise EmailAlreadyRegistered

    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(email: str, password: str, db: Session) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Conta desativada")

    # Migração transparente: senha legada SHA-256 bateu → rehash para bcrypt
    if is_legacy_hash(user.password_hash):
        try:
            user.password_hash = hash_password(password)
            db.commit()
            logger.info("Hash legado SHA-256 migrado para bcrypt: user_id=%s", user.id)
        except Exception:
            db.rollback()
            logger.exception("Falha ao migrar hash legado do user_id=%s", user.id)

    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Dependência FastAPI — extrai o usuário autenticado do token JWT."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token não fornecido")

    payload = decode_token(credentials.credentials)
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta desativada")
    return user


def require_role(*roles: UserRole):
    """Dependência que exige um dos roles informados. Use em rotas admin/debug."""
    allowed = {r.value if isinstance(r, UserRole) else r for r in roles}

    def _checker(user: User = Depends(get_current_user)) -> User:
        if (user.role.value if hasattr(user.role, "value") else user.role) not in allowed:
            raise HTTPException(status_code=403, detail="Acesso negado: role insuficiente")
        return user

    return _checker


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User | None:
    """Dependência opcional — retorna None se não autenticado."""
    if not credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        return db.query(User).filter(User.id == int(payload["sub"])).first()
    except HTTPException:
        return None
