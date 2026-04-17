"""Bootstrap de schema: usa Alembic quando disponível, fallback para create_all.

Substitui o `Base.metadata.create_all(bind=engine)` que rodava direto no import.
"""

import json
import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy import inspect

from app.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)


def reap_stuck_enrich_jobs(max_runtime_hours: int = 1) -> int:
    """Marca como `failed` EnrichJobs que ficaram presos em `running` após reboot.

    Rodar no startup garante que SIGTERM/OOM/scale-down não deixa jobs zumbis.
    Retorna o número de jobs reapados.
    """
    from app.models import EnrichJob, EnrichJobStatus
    from app.models import _utcnow as utcnow

    cutoff = utcnow() - timedelta(hours=max_runtime_hours)
    db = SessionLocal()
    try:
        stuck = (
            db.query(EnrichJob)
            .filter(EnrichJob.status == EnrichJobStatus.running)
            .filter(
                (EnrichJob.started_at.is_(None)) | (EnrichJob.started_at < cutoff)
            )
            .all()
        )
        for job in stuck:
            job.status = EnrichJobStatus.failed
            job.finished_at = utcnow()
            job.error_details = json.dumps({"error": "worker_restart"})
        if stuck:
            db.commit()
            logger.warning("Reaper: %d EnrichJob(s) zumbi(s) marcado(s) failed", len(stuck))
        return len(stuck)
    except Exception:
        db.rollback()
        logger.exception("Reaper falhou — continuando startup")
        return 0
    finally:
        db.close()


def _alembic_config():
    from alembic.config import Config

    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini_path))
    # sobrescreve a URL do ini com a da app (fonte da verdade: settings)
    from app.config import settings
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def run_migrations() -> None:
    """Garante que o schema está up-to-date.

    - Banco novo: cria tudo via metadata e marca head no alembic_version.
    - Banco já alembicado: aplica upgrade head.
    - Banco antigo (pré-alembic): cria versioning e marca head (schema já veio
      do create_all legado; migrações futuras partem daqui).
    """
    try:
        from alembic import command  # noqa: F401
    except ImportError:
        logger.warning("Alembic não instalado — usando create_all (dev fallback)")
        Base.metadata.create_all(bind=engine)
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    cfg = _alembic_config()

    if "alembic_version" in tables:
        # Base já tem versioning — aplica upgrade e garante que tabelas
        # declaradas no modelo mas ausentes no DB existam (idempotente).
        from alembic import command
        command.upgrade(cfg, "head")
        Base.metadata.create_all(bind=engine)
        return

    if tables - {"alembic_version"}:
        # Banco pré-alembic com schema existente: cria tabelas faltantes
        # e stampa head para começar a versionar a partir daqui.
        Base.metadata.create_all(bind=engine)
        from alembic import command
        command.stamp(cfg, "head")
        logger.info("Banco existente marcado em head do Alembic")
        return

    # Banco vazio: cria tudo e stampa head
    Base.metadata.create_all(bind=engine)
    from alembic import command
    command.stamp(cfg, "head")
    logger.info("Banco novo criado e marcado em head do Alembic")
