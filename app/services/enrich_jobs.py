"""Worker in-process para bulk-enrich.

Usa threading + SessionLocal próprio para liberar o request HTTP. Para escala
real (muitos clientes, lotes grandes), substituir por RQ/Celery/arq usando o
Redis já disponível — a tabela EnrichJob já suporta essa evolução sem mudança
de contrato do endpoint.
"""

import json
import logging
import threading
from typing import Callable

from app.database import SessionLocal
from app.models import EnrichJob, EnrichJobStatus, ImportItem, ItemStatus, Product
from app.models import _utcnow as utcnow

logger = logging.getLogger(__name__)


def _run_job(job_id: int):
    """Processa um EnrichJob. Roda em thread separada com SessionLocal próprio."""
    from app.services.ai_enrichment import enrich_product as ai_enrich

    db = SessionLocal()
    job: EnrichJob | None = None
    try:
        job = db.query(EnrichJob).filter(EnrichJob.id == job_id).first()
        if not job:
            logger.warning("EnrichJob %s desapareceu antes de rodar", job_id)
            return

        job.status = EnrichJobStatus.running
        job.started_at = utcnow()
        db.commit()

        items = (
            db.query(ImportItem)
            .filter(ImportItem.batch_id == job.batch_id)
            .filter(ImportItem.status.in_([ItemStatus.imported, ItemStatus.normalized]))
            .all()
        )

        errors: list[dict] = []
        for item in items:
            product = db.query(Product).filter(Product.import_item_id == item.id).first()
            if not product:
                continue
            try:
                ai_enrich(product, db)
                job.succeeded += 1
            except Exception as exc:
                logger.warning("Enriquecimento falhou para OEM %s: %s", product.oem, exc)
                errors.append({"oem": product.oem, "error": str(exc)[:200]})
                job.failed += 1

            job.processed += 1
            # commit parcial por item para manter progresso visível
            db.commit()

        job.error_details = json.dumps(errors, ensure_ascii=False) if errors else None
        job.status = EnrichJobStatus.completed
        job.finished_at = utcnow()
        db.commit()

    except Exception as exc:
        logger.exception("Falha catastrófica em EnrichJob %s", job_id)
        if job:
            try:
                job.status = EnrichJobStatus.failed
                job.error_details = json.dumps({"error": str(exc)[:500]})
                job.finished_at = utcnow()
                db.commit()
            except Exception:
                db.rollback()
    finally:
        db.close()


def enqueue_bulk_enrich(job_id: int, run: Callable[[int], None] = _run_job) -> None:
    """Dispara a thread de processamento em background."""
    thread = threading.Thread(target=run, args=(job_id,), daemon=True)
    thread.start()
