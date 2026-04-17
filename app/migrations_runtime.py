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


def run_all():
    migrate_ai_provider_configs()
