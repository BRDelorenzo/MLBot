"""Criptografia simétrica para tokens sensíveis usando Fernet."""

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet  # noqa: PLW0603
    if _fernet is None:
        if not settings.encryption_key:
            raise RuntimeError(
                "ENCRYPTION_KEY não configurada. "
                "Gere com: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        _fernet = Fernet(settings.encryption_key.encode())
    return _fernet


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Falha ao descriptografar token. ENCRYPTION_KEY pode ter mudado.") from exc
