"""Política de senha: mínimo 12 caracteres, complexidade mínima e blocklist.

HIBP via k-anonymity (B3 pós-launch). Esta camada já bloqueia as senhas mais
quebradas em qualquer brute-force offline realista.
"""

import re

from fastapi import HTTPException

MIN_LENGTH = 12
# bcrypt trunca em 72 bytes silenciosamente — rejeitamos explicitamente acima disso.
MAX_BYTES = 72

# Top senhas tipicamente exploradas em wordlists; não é exaustivo — é o piso.
_BLOCKLIST = {
    "123456", "123456789", "12345678", "12345", "1234567", "password",
    "qwerty", "abc123", "password1", "password123", "111111", "123123",
    "iloveyou", "admin", "welcome", "letmein", "monkey", "dragon",
    "master", "hello", "freedom", "whatever", "trustno1", "qazwsx",
    "qwerty123", "senha", "senha123", "senha1234", "102030", "1q2w3e",
    "1q2w3e4r", "1qaz2wsx", "brasil", "corinthians", "flamengo",
    "palmeiras", "saopaulo", "vasco", "gremio", "internacional",
    "mudar123", "mercadolivre", "mercadolibre", "mlbot", "mlbot123",
    "admin123", "admin1234", "administrator", "root", "root123",
    "teste", "teste123", "test1234", "changeme", "changeme123",
}


def _has_diversity(password: str) -> bool:
    """Exige pelo menos 3 das 4 classes: minúscula, maiúscula, dígito, símbolo."""
    classes = [
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"\d", password)),
        bool(re.search(r"[^\w\s]", password)),
    ]
    return sum(classes) >= 3


def validate_password(password: str) -> None:
    """Valida a senha ou levanta HTTPException 400 com mensagem específica."""
    if len(password) < MIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Senha deve ter no mínimo {MIN_LENGTH} caracteres.",
        )
    if len(password.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Senha muito longa (máx {MAX_BYTES} bytes — bcrypt trunca acima disso).",
        )
    if password.lower() in _BLOCKLIST:
        raise HTTPException(
            status_code=400,
            detail="Senha aparece em listas de senhas comuns. Escolha outra.",
        )
    if not _has_diversity(password):
        raise HTTPException(
            status_code=400,
            detail=(
                "Senha deve conter pelo menos 3 dos 4 tipos: "
                "letras minúsculas, maiúsculas, números e símbolos."
            ),
        )
