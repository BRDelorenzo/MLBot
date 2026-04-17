"""Métricas de negócio — Prometheus scrape endpoint.

Expõe contadores agregados (não-PII) para Grafana/Prometheus:
- anúncios publicados (total e por dia)
- enriquecimentos de produto
- falhas de publicação ML

Scraper: GET /metrics (admin-only). Em dev, ligue Prometheus com:
  - job_name: mlbot
    static_configs:
      - targets: ["localhost:8000"]
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    EnrichJob,
    EnrichJobStatus,
    ImportItem,
    ItemStatus,
    Listing,
    ListingStatus,
    User,
    UserRole,
)
from app.services.auth import require_role

router = APIRouter(tags=["metrics"])


def _render(name: str, help_text: str, kind: str, samples: list[tuple[str, float]]) -> str:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
    for labels, value in samples:
        suffix = f"{{{labels}}}" if labels else ""
        lines.append(f"{name}{suffix} {value}")
    return "\n".join(lines) + "\n"


@router.get("/metrics")
def prometheus_metrics(
    _user: User = Depends(require_role(UserRole.admin)),
    db: Session = Depends(get_db),
):
    published = (
        db.query(func.count(Listing.id))
        .filter(Listing.status == ListingStatus.published)
        .scalar()
        or 0
    )
    publish_errors = (
        db.query(func.count(Listing.id))
        .filter(Listing.status == ListingStatus.publish_error)
        .scalar()
        or 0
    )
    enriched_items = (
        db.query(func.count(ImportItem.id))
        .filter(ImportItem.status.in_([
            ItemStatus.enriched,
            ItemStatus.awaiting_review,
            ItemStatus.awaiting_photos,
            ItemStatus.processed,
            ItemStatus.validating,
            ItemStatus.ready_to_publish,
            ItemStatus.published,
        ]))
        .scalar()
        or 0
    )
    jobs_failed = (
        db.query(func.count(EnrichJob.id))
        .filter(EnrichJob.status == EnrichJobStatus.failed)
        .scalar()
        or 0
    )

    body = "".join([
        _render("mlbot_listings_published_total",
                "Total de anúncios publicados com sucesso", "counter",
                [("", published)]),
        _render("mlbot_listings_publish_errors_total",
                "Total de anúncios com erro de publicação", "counter",
                [("", publish_errors)]),
        _render("mlbot_products_enriched_total",
                "Total de produtos que passaram por enriquecimento IA", "counter",
                [("", enriched_items)]),
        _render("mlbot_enrich_jobs_failed_total",
                "Total de jobs de enriquecimento falhados", "counter",
                [("", jobs_failed)]),
    ])
    return Response(content=body, media_type="text/plain; version=0.0.4")
