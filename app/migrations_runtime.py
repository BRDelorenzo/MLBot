"""Migrações leves em runtime para esquemas que ainda não estão em Alembic.

Substituído por Alembic: DDL destrutivo em produção é bloqueado.
Remover este arquivo após primeira release prod (finding M13).
"""
import logging

from sqlalchemy import inspect, text

from app.config import settings
from app.database import engine

logger = logging.getLogger(__name__)


def migrate_ai_provider_configs():
    """Adiciona coluna user_id em ai_provider_configs se não existir.

    Apenas dev/SQLite. Em produção, migrações são via Alembic (0004_).
    """
    inspector = inspect(engine)
    if "ai_provider_configs" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("ai_provider_configs")}
    if "user_id" in columns:
        return

    if settings.env.lower() == "production":
        raise RuntimeError(
            "Migração destrutiva (DROP TABLE ai_provider_configs) bloqueada em "
            "produção. Aplique via migração Alembic dedicada."
        )

    logger.warning(
        "Migrando ai_provider_configs para multi-tenant. "
        "Configurações existentes serão apagadas e precisam ser re-adicionadas."
    )

    with engine.begin() as conn:
        # SQLite dev-only: drop+recreate (create_all roda depois).
        conn.execute(text("DROP TABLE ai_provider_configs"))


def widen_ml_credential_token_columns():
    """Garante que as colunas de token de ml_credentials sejam TEXT.

    O modelo define access_token_encrypted/refresh_token_encrypted como Text, mas
    bancos criados em versões antigas (antes dessa definição) podem ter VARCHAR(255)
    — pequeno demais para o token cifrado com Fernet (~250 chars). Como o create_all
    não altera tabelas existentes, gravar o token nesse banco antigo gera DataError
    ("value too long"). O widening é NÃO-destrutivo e idempotente, seguro em prod.
    """
    inspector = inspect(engine)
    if "ml_credentials" not in inspector.get_table_names():
        return

    # SQLite não diferencia VARCHAR(n) de TEXT; só Postgres impõe o limite.
    if engine.dialect.name != "postgresql":
        return

    cols = {c["name"]: c for c in inspector.get_columns("ml_credentials")}
    targets = ("access_token_encrypted", "refresh_token_encrypted")

    for name in targets:
        col = cols.get(name)
        if col is None:
            continue
        if "TEXT" in str(col["type"]).upper():
            continue  # já é TEXT — nada a fazer
        logger.warning(
            "Widening ml_credentials.%s para TEXT (era %s)", name, col["type"]
        )
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE ml_credentials ALTER COLUMN {name} TYPE TEXT")
            )


def run_all():
    migrate_ai_provider_configs()
    widen_ml_credential_token_columns()
